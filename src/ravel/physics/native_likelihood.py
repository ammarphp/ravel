"""Byte-bound native CMS Combine likelihood worker.

Planning never executes a native command. The scientific-study lifecycle owns
approval, the hard time budget and process group. Native execution preserves the
complete supplied datacard and ROOT assets; it is not a pyhf approximation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import time

from ravel.physics import eft_functions as eft
from ravel.workflow.state_io import atomic_json, read_json

ENVIRONMENT = {"PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "PYTHONPATH", "ROOTSYS",
               "CMSSW_BASE", "CMSSW_RELEASE_BASE", "CMSSW_VERSION", "SCRAM_ARCH"}
METHODS = {"AsymptoticLimits", "MultiDimFit"}
RESERVED = {"ravel_workspace.root", "ravel_native_configuration.json", "ravel_native_probe.py",
            "ravel_native_result.py", "ravel_source_response.json", "ravel_source_response.py"}
FIXED_RESERVED = {"ravel_regional_fixed_state.py", "ravel_fixed_state_points.jsonl"}
EXPECTED_RESERVED = {"ravel_regional_expected.py", "ravel_expected_workspace.root", "ravel_expected_preparation.json", "ravel_expected_preparation.fit.root", "ravel_expected_crossing_request.json", "ravel_expected_crossings.json"}
DERIVATIVE_RESERVED = {"ravel_derivative_context.json", "ravel_derivative_kernel.py", "ravel_combine_derivatives.py", "ravel_derivative_points.jsonl"}


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " requires exactly " + ", ".join(sorted(keys)))


def _safe_relative(value):
    if not isinstance(value, str) or not value or PurePosixPath(value).is_absolute() or any(p in ("", ".", "..") for p in value.split("/")) or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in value.split("/")):
        raise ValueError("safe explicit staged relative path required")
    return value


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pin(pin, base, *, executable=False, _session=None):
    from ravel.workflow.science import regular
    _keys(pin, {"path", "sha256"}, "source/runtime pin")
    if not isinstance(pin["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]):
        raise ValueError("lowercase SHA256 required")
    path = regular(pin["path"], base, _session=_session)
    if (_session.hash_file if _session is not None else _hash)(path) != pin["sha256"] or executable and not os.access(path, os.X_OK):
        raise ValueError("changed source/runtime input or non-executable tool")
    return path


def _finite(value, label, *, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value) or positive and value <= 0:
        raise ValueError("finite " + ("positive " if positive else "") + label + " required")
    return float(value)


def _card_dependencies(raw, staged_card, file_names):
    """Resolve explicit shape/extended-argument assets without ambient paths."""
    parent = PurePosixPath(staged_card).parent
    shape_files = []
    for line in raw.decode().splitlines():
        tokens = line.split("#", 1)[0].split()
        if not tokens:
            continue
        candidate = None
        if tokens[0] == "shapes":
            if len(tokens) < 4:
                raise ValueError("malformed shapes directive")
            if tokens[3] == "FAKE":
                continue
            candidate = tokens[3]
        if len(tokens) > 2 and tokens[1] == "extArg":
            # Numeric extArg is internal. External file:workspace is explicit.
            try:
                eft.rational(tokens[2])
            except ValueError:
                if ":" not in tokens[2]:
                    raise ValueError("unresolved external argument source")
                candidate = tokens[2].split(":", 1)[0]
        if len(tokens) > 4 and tokens[1] == "rateParam" and ".root:" in tokens[4]:
            candidate = tokens[4].split(":", 1)[0]
        if candidate:
            _safe_relative(candidate)
            resolved = (parent / candidate).as_posix()
            if resolved not in file_names:
                raise ValueError("unbound datacard asset: " + resolved)
            shape_files.append(resolved)
    return list(dict.fromkeys(shape_files))


def replace_counting_signal(raw, replacement):
    """Replace all SR/CR rates and every signal nuisance entry explicitly.

    Shape assets require a separate source model. This counting-card operation
    refuses to preserve old signal uncertainties through an implicit rate edit.
    Background and auxiliary/transfer construction are retained byte-for-byte.
    """
    _keys(replacement, {"source", "columns"}, "counting signal replacement")
    if not isinstance(replacement["source"], str) or not replacement["source"].strip() or not isinstance(replacement["columns"], list):
        raise ValueError("scientific replacement source and complete columns required")
    census = eft.parse_datacard(raw)
    signal = [c for c in census["columns"] if c["process_id"] <= 0]
    columns = replacement["columns"]
    if len(columns) != len(signal):
        raise ValueError("replacement must cover every signal column, including all control regions")
    for original, new in zip(signal, columns):
        _keys(new, {"channel", "process", "rate", "nuisances"}, "replacement column")
        if (new["channel"], new["process"]) != (original["channel"], original["process"]):
            raise ValueError("replacement signal/CR column identity or order mismatch")
        if not isinstance(new["rate"], str) or eft.rational(new["rate"]) < 0 or not isinstance(new["nuisances"], dict):
            raise ValueError("nonnegative replacement and explicit signal uncertainty entries required")
    lines = raw.decode().splitlines(keepends=True)
    nuisance_rows = {}
    kinds = {"lnN", "lnU", "shape", "shapeN2", "gmN"}
    ncolumns = len(census["columns"])
    for index, line in enumerate(lines):
        tokens = line.split("#", 1)[0].split()
        if tokens and tokens[0] == "shapes" and len(tokens) >= 4 and tokens[3] != "FAKE":
            raise ValueError("counting replacement cannot substitute shape histograms or their uncertainties")
        if len(tokens) > 1 and tokens[1] in kinds:
            offset = 3 if tokens[1] == "gmN" else 2
            if len(tokens) != offset + ncolumns or tokens[0] in nuisance_rows:
                raise ValueError("nuisance column count or identity mismatch")
            nuisance_rows[tokens[0]] = (index, tokens, offset)
    for new in columns:
        if set(new["nuisances"]) != set(nuisance_rows):
            raise ValueError("every source signal nuisance row must be explicitly replaced, including '-' entries")
    rate_index = census["rate_line"] - 1
    rate_tokens = lines[rate_index].split("#", 1)[0].split()
    for old, new in zip(signal, columns):
        rate_tokens[old["index"] + 1] = new["rate"]
    lines[rate_index] = " ".join(rate_tokens) + "\n"
    for name, (index, tokens, offset) in nuisance_rows.items():
        for old, new in zip(signal, columns):
            token = new["nuisances"][name]
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError("single explicit nuisance token required")
            if token != "-":
                parts = token.split("/")
                if len(parts) not in (1, 2) or any(eft.rational(p) <= 0 for p in parts):
                    raise ValueError("positive native nuisance factor or '-' required")
            tokens[offset + old["index"]] = token
        lines[index] = " ".join(tokens) + "\n"
    changed = "".join(lines).encode()
    # Check unchanged background rate/nuisance tokens independently.
    updated = eft.parse_datacard(changed)
    for old, new in zip(census["columns"], updated["columns"]):
        if old["process_id"] > 0 and old != new:
            raise ValueError("background altered by signal replacement")
    return changed, {"source": replacement["source"], "source_sha256": census["sha256"],
                     "result_sha256": hashlib.sha256(changed).hexdigest(),
                     "replaced_signal_columns": len(signal), "replaced_nuisance_rows": list(nuisance_rows),
                     "scientific_validity": "Declared replacement evidence; detector and uncertainty validity unverified"}


def validate(task):
    if not isinstance(task, dict) or set(task) != {"input"} or not isinstance(task["input"], str) or not task["input"]:
        raise ValueError("native-likelihood task requires exactly input")


def _version_proof(runtime, base, *, _session=None):
    """Bind the source-defined no-datacard diagnostic, without executing it.

    Combine's help branch returns before its compiled version banner. The
    missing-datacard branch prints that banner and returns 1002 before seed
    initialization and algorithm configuration (234 as a POSIX exit status).
    This is a narrow source control, not a general C++ semantic verifier.
    """
    proof = runtime["version_proof"]
    _keys(proof, {"kind", "source", "expected_returncode"}, "Combine version proof")
    if proof["kind"] != "missing_datacard_diagnostic" or type(proof["expected_returncode"]) is not int or proof["expected_returncode"] != 1002 % 256:
        raise ValueError("source-defined missing-datacard diagnostic exit 234 required")
    source = _pin(proof["source"], base, _session=_session)
    if source.stat().st_size > 1024 * 1024:
        raise ValueError("bounded Combine version proof source required")
    raw = source.read_text()
    tags = re.findall(r'\bstd::string\s+combineTagString\s*=\s*"([^"]+)"\s*;', raw)
    branch = re.search(r'if\s*\(\s*datacard\s*==\s*""\s*\)\s*\{\s*cerr\s*<<\s*"Missing datacard file"\s*<<\s*endl\s*;[^{}]*\breturn\s+1002\s*;\s*\}', raw)
    seed = re.search(r'if\s*\(\s*seed\s*==\s*-1\s*\)', raw)
    configuration = raw.find("combiner.applyOptions")
    if tags != ["v" + runtime["expected"]["combine_version"]] or branch is None or seed is None or not branch.end() < seed.start() < configuration:
        raise ValueError("pinned Combine source does not establish the declared version diagnostic boundary")
    return source


def _combine_version_identity(log, version):
    tags = re.findall(r'^\s*<<< (v[^\s]+) >>>\s*$', log, re.MULTILINE)
    banners = re.findall(r'^\s*<<< Combine >>>\s*$', log, re.MULTILINE)
    missing = re.findall(r'^Missing datacard file\s*$', log, re.MULTILINE)
    if tags != ["v" + version] or len(banners) != 1 or len(missing) != 1:
        raise ValueError("actual Combine diagnostic did not establish exactly the pinned compiled version and missing-datacard boundary")
    return {"combine_version": version, "kind": "missing_datacard_diagnostic", "expected_returncode": 234}


def _validate_saved_fit(fit):
    """Closed v2 best-fit diagnostic, never a grid/interval or retry policy."""
    if fit["method"] != "MultiDimFit" or fit["data"] != "observed" or fit["points"] is not None or fit["reference_quantiles"] is not None:
        raise ValueError("saved-fit v2 requires one observed MultiDimFit best fit, without grid or limit references")
    saved = fit["saved_fit"]
    _keys(saved, {"algorithm", "required_object", "maximum_edm"}, "saved-fit diagnostic")
    if saved["algorithm"] != "none" or saved["required_object"] != "multidimfit.ravel.root:fit_mdf":
        raise ValueError("source-defined none algorithm and exact saved fit_mdf object required")
    if not 0 < _finite(saved["maximum_edm"], "prospective maximum EDM") <= .001:
        raise ValueError("saved-fit EDM engineering ceiling must be positive and at most 0.001")


def _extract_saved_fit_row(rows, fit):
    if len(rows) != 1 or not {fit["poi"], "deltaNLL", "quantileExpected"} <= set(rows[0]):
        raise ValueError("saved best fit requires exactly one literal POI/deltaNLL/quantile row")
    row = rows[0]
    lower, upper = [float(eft.rational(p)) for p in fit["domain"]]
    tolerance = 1e-6 * max(1., abs(lower), abs(upper))
    if not lower-tolerance <= row[fit["poi"]] <= upper+tolerance or abs(row["quantileExpected"]+1) > 1e-5:
        raise ValueError("saved best-fit row has wrong POI domain or quantile identity")
    suspect = abs(row["deltaNLL"]) > 1e-6 or any(row.get(k,0) != 0 for k in ("fit_status","fitStatus","status"))
    return {"kind": "native_saved_best_fit_diagnostics", "poi": fit["poi"], "rows": rows,
            "passed": not suspect, "suspect_fit_rows": [0] if suspect else [],
            "scope": "One free-POI native best fit with saved diagnostics; no per-grid convergence, globality or interval"}


def _extract_saved_diagnostics(inference, diagnostics, fit):
    saved = fit["saved_fit"]
    criteria = {"exactly_one_saved_result": len(diagnostics) == 1}
    suspect = []
    for row in diagnostics:
        _keys(row, {"name", "status", "covariance_quality", "edm", "minimum_nll", "invalid_nll_evaluations", "status_history", "floating_parameters", "constant_parameters"}, "saved-fit v2 RooFitResult")
        if not isinstance(row["name"], str) or not row["name"]:
            raise ValueError("literal nonempty saved result name required")
        if any(type(row[k]) is not int for k in ("status","covariance_quality","invalid_nll_evaluations")) or row["invalid_nll_evaluations"] < 0:
            raise ValueError("saved-fit statuses and invalid-evaluation census require literal integers")
        _finite(row["minimum_nll"], "saved minimum NLL")
        edm = _finite(row["edm"], "saved fit EDM")
        history = row["status_history"]
        if not isinstance(history,list): raise ValueError("saved status history must be an explicit list")
        for step in history:
            _keys(step,{"label","status"},"saved status history step")
            if not isinstance(step["label"],str) or not step["label"] or type(step["status"]) is not int: raise ValueError("malformed saved status history")
        names = set()
        floated = {}
        for group in ("floating_parameters","constant_parameters"):
            parameters = row[group]
            if not isinstance(parameters,list) or len(parameters)>10000: raise ValueError("bounded saved parameter lists required")
            for parameter in parameters:
                _keys(parameter,{"name","value","error"} if group=="floating_parameters" else {"name","value"},"saved parameter")
                name = parameter["name"]
                if not isinstance(name,str) or not name or name in names: raise ValueError("duplicate or invalid saved parameter identity")
                names.add(name); _finite(parameter["value"],"saved parameter value")
                if group=="floating_parameters":
                    if _finite(parameter["error"],"saved parameter error") < 0: raise ValueError("negative saved parameter error")
                    floated[name] = parameter
        if fit["poi"] not in floated: raise ValueError("free POI missing from saved floating parameters")
        domain = [float(eft.rational(p)) for p in fit["domain"]]
        poi_tolerance = 1e-6 * max(1.,*(abs(p) for p in domain))
        actual_poi = floated[fit["poi"]]["value"]
        checks = {"exact_saved_object": row["name"] == saved["required_object"],
                  "status_zero": row["status"] == 0, "full_covariance_quality": row["covariance_quality"] == 3,
                  "edm_within_predeclared_ceiling": 0 <= edm <= saved["maximum_edm"],
                  "no_invalid_nll_evaluations": row["invalid_nll_evaluations"] == 0,
                  "nonempty_clean_status_history": bool(history) and all(s["status"]==0 for s in history),
                  "saved_poi_matches_tree": abs(actual_poi-inference["rows"][0][fit["poi"]]) <= poi_tolerance,
                  "saved_poi_in_domain": domain[0] <= actual_poi <= domain[1]}
        if not all(checks.values()): suspect.append(row["name"])
        criteria.setdefault("results",[]).append(checks)
    inference["fit_diagnostics"] = {"saved_fit_results": diagnostics, "saved_result_available": bool(diagnostics),
        "suspect_results": suspect, "criteria": criteria, "maximum_edm": saved["maximum_edm"],
        "scope": "Predeclared local best-fit engineering diagnostics: status0/covQual3/EDM and invalid-NLL/history gates. Neither globality nor per-grid convergence is established."}
    inference["passed"] = inference["passed"] and criteria["exactly_one_saved_result"] and not suspect
    return inference


def _check_saved_population(inference, probe):
    """Require the saved parameter census to cover this actual POI/nuisance set."""
    diagnostics = inference["fit_diagnostics"]
    if not diagnostics["saved_result_available"]:
        diagnostics["actual_model_parameter_coverage"] = False
        return
    row = diagnostics["saved_fit_results"][0]
    saved = {p["name"] for group in ("floating_parameters","constant_parameters") for p in row[group]}
    expected = set(probe["workspace"]["pois"]) | set(probe["workspace"]["nuisances"])
    missing = sorted(expected-saved)
    diagnostics["actual_model_parameter_coverage"] = not missing
    diagnostics["missing_actual_model_parameters"] = missing
    inference["passed"] = inference["passed"] and not missing


def _configuration(task, base, *, _session=None):
    from ravel.workflow.science import regular
    validate(task)
    cp = regular(task["input"], base, _session=_session)
    config = _session.read_document(cp) if _session is not None else read_json(cp)
    derivative_only = type(config) is dict and config.get("schema_version") == 3
    expected_only = "expected_data" in config
    calibration = "calibration" in config
    discovery = "discovery_diagnostic" in config
    fixed_observer = derivative_only and "fixed_state_observer" in config
    _keys(config, {"schema_version", "source", "model", "runtime", "fit", "max_seconds"} | ({"derivatives"} if derivative_only else set()) | ({"fixed_state_observer"} if fixed_observer else set()) | ({"expected_data"} if expected_only else set()) | ({"calibration"} if calibration else set()) | ({"discovery_diagnostic"} if discovery else set()), "native-likelihood/v1, saved-fit/v2 or fixed-NLL derivatives/v3")
    if type(config["schema_version"]) is not int or config["schema_version"] not in (1, 2, 3) or not isinstance(config["source"], str) or not config["source"].strip() or type(config["max_seconds"]) is not int or not 1 <= config["max_seconds"] <= 86400:
        raise ValueError("valid source/schema and bounded native budget required")
    base = cp.parent
    model = config["model"]
    construction = type(model) is dict and "construction" in model
    source_graph = type(model) is dict and "source_graph" in model
    if source_graph and (construction or model.get("physics_model") is not None or model.get("signal_replacement") is not None):
        raise ValueError("source graph is a distinct observed native route; derivative/expected/calibration labels require separate qualification")
    _keys(model, {"files", "card", "regions", "physics_model", "signal_replacement"} | ({"construction"} if construction else set()) | ({"source_graph"} if source_graph else set()), "native model")
    if not isinstance(model["files"], list) or not model["files"]:
        raise ValueError("complete native file graph required")
    files = {}
    for row in model["files"]:
        _keys(row, {"path", "sha256", "staged_path"}, "model file")
        name = _safe_relative(row["staged_path"])
        if discovery and (name.startswith('ravel_discovery_heldout') or name=='ravel_graph_state.py'):
            raise ValueError('discovery helper/journal/fit output is reserved')
        if (calibration and (name.startswith("ravel_calibration_") or name in {"ravel_regional_calibration.py", "ravel_regional_expected.py","ravel_source_graph_calibration.py","ravel_graph_state.py"})) or (expected_only and name.split("/")[0].startswith("ravel_expected_profile_")) or name.split("/")[0] in RESERVED | (EXPECTED_RESERVED if expected_only else set()) | (DERIVATIVE_RESERVED if derivative_only else set()) | (FIXED_RESERVED if fixed_observer else set()) or name in files or any(name == p or name.startswith(p + "/") or p.startswith(name + "/") for p in files):
            raise ValueError("duplicate or conflicting staged model path")
        if PurePosixPath(name).name.startswith(("higgsCombine.ravel.", "multidimfit.ravel")):
            raise ValueError("generated native output basename is reserved")
        files[name] = _pin({k: row[k] for k in ("path", "sha256")}, base, _session=_session)
    card_name = _safe_relative(model["card"])
    if card_name not in files:
        raise ValueError("card must be a pinned source file")
    raw = files[card_name].read_bytes()
    card = eft.parse_datacard(raw)
    dependencies = _card_dependencies(raw, card_name, files)
    regions = model["regions"]
    if not isinstance(regions, list) or len(regions) != len(card["channels"]):
        raise ValueError("every native card region requires an explicit SR/CR role")
    for channel, row in zip(card["channels"], regions):
        _keys(row, {"channel", "role"}, "region")
        if row["channel"] != channel or row["role"] not in (("signal_region", "control_region", "mc_auxiliary") if construction or source_graph else ("signal_region", "control_region")):
            raise ValueError("complete ordered SR/CR identity required")
    physics_path, response, response_binding = None, None, None
    if model["physics_model"] is not None:
        physics_path = _pin(model["physics_model"], base, _session=_session)
        response = eft.parse_source(physics_path.read_bytes())
        response_binding = eft.bind_card(response, card)
        if model["signal_replacement"] is not None:
            raise ValueError("EFT source response cannot be combined with a counting rate substitution")
    if source_graph:
        from ravel.physics import native_statistical_construction as graph
        _keys(model["source_graph"], {"recipe", "cell"}, "source graph selection")
        physics_path = _pin(model["source_graph"]["recipe"], base, _session=_session)
        document = _session.read_document(physics_path) if _session is not None else read_json(physics_path)
        graph.source_inputs(document, physics_path.parent, _session=_session)
        response = graph.response(document, model["source_graph"]["cell"])
        selected = next(c for c in document['cells'] if c['id']==model['source_graph']['cell'])
        if derivative_only != ('derivatives' in selected) or derivative_only and config['derivatives'] != selected['derivatives']:
            raise ValueError('native diagnostics changed the authenticated original cell operation')
        if calibration != ('calibration' in selected) or calibration and config['calibration'] != selected['calibration']:
            raise ValueError('native calibration changed the authenticated original cell operation')
        if discovery != ('discovery_diagnostic' in selected) or discovery and config['discovery_diagnostic']!=selected['discovery_diagnostic']:
            raise ValueError('native discovery changed the authenticated original source cell')
        if derivative_only and fixed_observer:
            raise ValueError('regional fixed-state reference labels do not apply to source graph diagnostics')
        if config['runtime'] != document['runtime'] or config['fit'] != selected['fit'] or config['max_seconds'] != document['max_seconds'] or config['source'] != document['question']:
            raise ValueError('native task changed the reviewed original cell fit/runtime/resources/source')
        if card_name != graph.CARD or raw != graph.datacard(document, model["source_graph"]["cell"]) or regions != [{"channel":b["id"],"role":b["role"]} for b in response["document"]["bins"]]:
            raise ValueError("source graph card/complete SR/CR population changed")
        expected_sources = {"source/"+r["path"]:r["sha256"] for r in document["source_capsule"]["files"]}
        if set(files) != {card_name,*expected_sources} or any((_session.hash_file(files[n]) if _session is not None else _hash(files[n])) != sha for n,sha in expected_sources.items()):
            raise ValueError("source graph native bundle omitted/changed original source, template or variation files")
        response_binding = {"kind":graph.KIND,"recipe_sha256":_hash(physics_path),"cell":model["source_graph"]["cell"],"source_law":response["law"],"numerical_equivalence_qualified":False,"expected_data_qualified":False,"calibration_qualified":False}
    if construction:
        from ravel.physics import statistical_construction as regional
        if config["schema_version"] not in (1, 2, 3) or model["physics_model"] is not None or model["signal_replacement"] is not None:
            raise ValueError("construction requires an observed native profile, saved fit or fixed NLL route without EFT source or rate replacement")
        physics_path = _pin(model["construction"], base, _session=_session)
        document = _session.read_document(physics_path) if _session is not None else read_json(physics_path)
        regional.source_inputs(document, physics_path.parent, _session=_session)
        if raw != regional.datacard(document):
            raise ValueError("native card is not the complete declared regional construction")
        if regions != [{"channel": b["id"], "role": b["role"]} for b in document["bins"]]:
            raise ValueError("construction SR/CR population differs")
        response = regional.response(document)
        response_binding = {"kind": regional.KIND, "construction_sha256": _hash(physics_path), "source_law": response["law"]}
    if expected_only:
        from ravel.physics import regional_expected
        if source_graph:
            from ravel.physics import native_statistical_construction as graph
            if config['expected_data']!=selected.get('expected_data') or config['expected_data']!=graph.expected_request(selected) or config['fit']['method']!='MultiDimFit' or config['fit']['data']!='source_asimov': raise ValueError('source graph expected declaration/profile differs')
        else:
            if not construction or config["schema_version"]!=1 or config["expected_data"]!=document.get("expected_data"):
                raise ValueError("expected-only data must match the complete regional source prescription")
            regional_expected.validate_fit(document, config["fit"])
    elif source_graph and 'expected_data'in selected:
        raise ValueError('source graph Asimov prescription cannot masquerade as observed data')
    elif construction and "expected_data" in document:
        raise ValueError("expected construction cannot masquerade as observed inference")
    if discovery:
        from ravel.physics import discovery_heldout
        if not source_graph or not expected_only or derivative_only or calibration:
            raise ValueError('discovery uses one source graph nominal Asimov dataset and separate paired profiles')
        discovery_heldout.validate(config['discovery_diagnostic'],selected,regional_expected.PROFILE_POLICY)
        if config['runtime']['expected']['root_version']!='6.22/00':
            raise ValueError('current source graph/profile API binds exact ROOT6.22; no guessed version compatibility')
    if calibration:
        from ravel.physics import regional_calibration
        if not (construction or source_graph) or expected_only or config["schema_version"] != 2 or config["fit"]["data"] != "observed":
            raise ValueError("full auxiliary calibration requires a complete observed regional construction and saved-fit runtime")
        if source_graph:
            from ravel.physics import source_graph_calibration
            source_graph_calibration.validate(config["calibration"],response)
        elif regional_calibration.has_dijet(document):
            # Same admitted C29 kernel and complete signed mean law. The native
            # returned means are still checked at truth and both fitted states;
            # do not perform an unreserved second quadrature via mean_jet here.
            response_binding['calibration_reference_admission'] = regional_calibration.reference_admission(config['calibration'], document)
        else:
            regional_calibration.validate(config["calibration"], document)
            for truth in config["calibration"]["truths"]:
                jet = regional.mean_jet(document, truth["point"])
                observed_means = regional_calibration.means(document, truth["point"])
                if any(abs(observed_means[b['id']]-v)>1e-10*(1+abs(v)) for b,v in zip(document['bins'],jet['means'])):
                    raise ValueError("calibration generating law differs from full source construction")
    replacement_receipt = None
    if model["signal_replacement"] is not None:
        raw, replacement_receipt = replace_counting_signal(raw, model["signal_replacement"])
    runtime = config["runtime"]
    _keys(runtime, {"tools", "artifacts", "environment", "expected", "transport", "version_proof"}, "native runtime")
    _keys(runtime["tools"], {"combine", "text2workspace", "python"}, "native tools")
    transport = runtime["transport"]
    if not isinstance(transport, dict) or transport.get("kind") not in ("local", "podman"):
        raise ValueError("explicit local or digest-bound Podman transport required")
    if transport["kind"] == "local":
        _keys(transport, {"kind"}, "local transport")
        tools = {key: _pin(value, base, executable=True, _session=_session) for key, value in runtime["tools"].items()}
    else:
        _keys(transport, {"kind", "executable", "connection", "image_archive", "image_manifest", "image_id", "manifest_digest", "client_environment"}, "Podman transport")
        _pin(transport["executable"], base, executable=True, _session=_session)
        _pin(transport["image_archive"], base, _session=_session)
        manifest_path = _pin(transport["image_manifest"], base, _session=_session)
        manifest = read_json(manifest_path)
        if not isinstance(transport["manifest_digest"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", transport["manifest_digest"]) or "sha256:" + (_session.hash_file if _session is not None else _hash)(manifest_path) != transport["manifest_digest"] or transport["image_id"] != manifest.get("config", {}).get("digest"):
            raise ValueError("Podman source manifest/config digest binding differs")
        if not isinstance(transport["connection"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", transport["connection"]):
            raise ValueError("one explicit owned Podman connection required")
        ce = transport["client_environment"]
        if not isinstance(ce, dict) or set(ce) - {"HOME", "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CONTAINERS_MACHINE_PROVIDER"} or not {"HOME", "PATH"} <= set(ce) or any(not isinstance(v, str) or "\x00" in v for v in ce.values()):
            raise ValueError("explicit bounded Podman client environment required")
        def image_pin(value):
            _keys(value, {"path", "sha256"}, "image file pin")
            if not isinstance(value["path"], str) or not value["path"].startswith("/") or ".." in PurePosixPath(value["path"]).parts or not isinstance(value["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"]):
                raise ValueError("absolute source-image file and SHA256 required")
            return Path(value["path"])
        tools = {key: image_pin(value) for key, value in runtime["tools"].items()}
    if not isinstance(runtime["artifacts"], list) or not runtime["artifacts"]:
        raise ValueError("explicit nonempty native library/module/ABI artifact pins required")
    artifacts = [(_pin(value, base, _session=_session) if transport["kind"] == "local" else image_pin(value)) for value in runtime["artifacts"]]
    if len(set(artifacts)) != len(artifacts):
        raise ValueError("duplicate runtime artifact")
    if sum(p.name == "PhysicsModel.py" for p in artifacts) != 1 or sum(p.name in ("libHiggsAnalysisCombinedLimit.so", "libHiggsAnalysisCombinedLimit.dylib") for p in artifacts) != 1:
        raise ValueError("pin the actual PhysicsModel.py and native Combine custom-class library")
    environment = runtime["environment"]
    if not isinstance(environment, dict) or set(environment) - ENVIRONMENT or "PATH" not in environment or any(not isinstance(v, str) or "\x00" in v for v in environment.values()):
        raise ValueError("explicit bounded native environment including PATH required")
    expected = runtime["expected"]
    _keys(expected, {"combine_version", "root_version", "cmssw_version", "architecture", "custom_classes"}, "runtime expectations")
    if any(not isinstance(expected[k], str) or not expected[k] for k in ("combine_version", "root_version", "architecture")) or expected["cmssw_version"] is not None and not isinstance(expected["cmssw_version"], str) or not isinstance(expected["custom_classes"], list) or not expected["custom_classes"] or any(not re.fullmatch(eft.IDENTIFIER, c) for c in expected["custom_classes"]):
        raise ValueError("explicit native version/architecture/custom-class expectations required")
    if expected_only and expected["root_version"]!="6.22/00":
        raise ValueError("expected-only preparation currently binds ROOT6.22/00 source/API semantics")
    if calibration and source_graph:
        for stem in ('libMathCore','libRIO'):
            if sum(p.name in (stem+'.so',stem+'.dylib') for p in artifacts)!=1:
                raise ValueError('explicit pinned '+stem+' artifact required for graph sampler/state APIs')
        if not {'TRandom3','TBufferJSON'} <= set(expected['custom_classes']):
            raise ValueError('explicit graph native sampler/state classes required')
    if calibration and expected["root_version"] != "6.22/00":
        raise ValueError("calibration currently binds the reviewed ROOT6.22 regional global/optimizer API")
    if source_graph and (expected["combine_version"] != "9.2.1" or expected["root_version"] != "6.22/00"):
        raise ValueError("source graph integration/lowering currently pins Combine9.2.1 and ROOT6.22/00 APIs")
    if construction and expected["combine_version"] != "9.2.1":
        raise ValueError("regional lowering source policy currently covers Combine 9.2.1 only")
    _version_proof(runtime, base, _session=_session)
    fit = config["fit"]
    fit_keys = {"method", "data", "poi", "domain", "mass", "seed", "points", "minimizer", "fixed_witness_points", "reference_quantiles"}
    saved = config["schema_version"] == 2
    _keys(fit, fit_keys | ({"saved_fit"} if saved else set()) | ({"absolute_nll"} if "absolute_nll" in fit else set()), "native fit")
    if "absolute_nll" in fit:
        _validate_absolute_scan(config)
    if saved:
        _validate_saved_fit({**fit,'data':'observed'} if source_graph and expected_only else fit)
    if discovery and (saved or fit['minimizer'] is not None or fit['reference_quantiles'] is not None or fit['fixed_witness_points'] or fit['method']!='MultiDimFit'):
        raise ValueError('discovery uses only the declared existing profile policy and paired readbacks; no hidden native witness/grid/reference work')
    if calibration and (fit["minimizer"] is not None or fit["saved_fit"]["maximum_edm"] != .00001):
        raise ValueError("calibration reuses the exact existing profile policy; no alternate fit settings")
    if derivative_only:
        from ravel.physics.combine_derivatives import validate_selection, ROOT_SOURCE_POLICIES
        if expected["root_version"] not in ROOT_SOURCE_POLICIES:
            raise ValueError("source-qualified exact ROOT version required for derivative global semantics")
        validate_selection(config["derivatives"])
        if fixed_observer:
            from ravel.physics import regional_fixed_state
            regional_fixed_state.validate_request(config["fixed_state_observer"], response)
        if (fit["method"] != "MultiDimFit" or fit["data"] != ("source_asimov" if source_graph and expected_only else "observed") or fit["points"] is not None
            or fit["minimizer"] is not None or fit["reference_quantiles"] is not None or fit["fixed_witness_points"] != []):
            raise ValueError("derivative v3 requires observed fixed NLL only, without fit/grid/minimizer/reference or extra witness calls")
    if fit["method"] not in METHODS or fit["data"] not in (("observed", "asimov_background", "source_asimov") if source_graph and expected_only else ("observed", "asimov_background")) or not isinstance(fit["poi"], str) or not re.fullmatch(eft.IDENTIFIER, fit["poi"]):
        raise ValueError("supported native fit/data/POI required")
    if not isinstance(fit["domain"], list) or len(fit["domain"]) != 2 or not eft.rational(fit["domain"][0]) < eft.rational(fit["domain"][1]):
        raise ValueError("explicit ordered native POI domain required")
    native_domain = [_finite(float(eft.rational(p)), "native floating POI bound") for p in fit["domain"]]
    if native_domain[0] >= native_domain[1]:
        raise ValueError("native floating POI domain must preserve distinct ordered bounds")
    _finite(fit["mass"], "mass", positive=True)
    if type(fit["seed"]) is not int or not 1 <= fit["seed"] <= 2147483646:
        raise ValueError("positive fixed Combine seed required")
    if saved or derivative_only or discovery:
        if fit["points"] is not None:
            raise ValueError("saved best fit has no profile grid point count")
    elif fit["method"] == "MultiDimFit":
        if type(fit["points"]) is not int or not 3 <= fit["points"] <= 100000:
            raise ValueError("bounded grid point count required")
    elif fit["points"] is not None or eft.rational(fit["domain"][0]) < 0:
        raise ValueError("AsymptoticLimits requires nonnegative signal strength and no grid points")
    if response and not expected_only:
        d = response["domain"]
        if fit["method"] != "MultiDimFit" or fit["data"] != "observed" or fit["poi"] != d["name"] or [eft.rational(p) for p in fit["domain"]] != [eft.rational(d[k]) for k in ("lower", "upper")]:
            raise ValueError("EFT uses native one-coefficient signed-domain profiling, without a monotonic upper-limit assumption")
    if not isinstance(fit["fixed_witness_points"], list) or not derivative_only and not discovery and not fit["fixed_witness_points"] or len(fit["fixed_witness_points"]) > 100 or any(not isinstance(p, str) for p in fit["fixed_witness_points"]):
        raise ValueError("bounded nonempty fixed native workspace witnesses required")
    if any(not eft.rational(fit["domain"][0]) <= eft.rational(p) <= eft.rational(fit["domain"][1]) for p in fit["fixed_witness_points"]):
        raise ValueError("fixed witness outside POI domain")
    minimizer = fit["minimizer"]
    if minimizer is not None:
        _keys(minimizer, {"strategy", "tolerance"}, "minimizer")
        if type(minimizer["strategy"]) is not int or minimizer["strategy"] not in (0, 1, 2):
            raise ValueError("native Minuit2 strategy must be zero, one or two")
        _finite(minimizer["tolerance"], "minimizer tolerance", positive=True)
    refs = fit["reference_quantiles"]
    if refs is not None:
        if fit["method"] != "AsymptoticLimits":
            raise ValueError("reference quantiles belong to native AsymptoticLimits only")
        _keys(refs, {"source", "values", "absolute_tolerance", "relative_tolerance"}, "reference quantiles")
        if not isinstance(refs["source"], str) or not refs["source"].strip():
            raise ValueError("attributable reference quantiles required")
        _keys(refs["values"], {"minus2sigma", "minus1sigma", "median", "plus1sigma", "plus2sigma", "observed"} if fit["data"] == "observed" else {"minus2sigma", "minus1sigma", "median", "plus1sigma", "plus2sigma"}, "reference values")
        for value in refs["values"].values():
            _finite(value, "reference limit", positive=True)
        for key in ("absolute_tolerance", "relative_tolerance"):
            if _finite(refs[key], "reference tolerance") < 0:
                raise ValueError("reference tolerance must be nonnegative")
    return config, cp, files, tools, artifacts, physics_path, card, raw, response, response_binding, dependencies, replacement_receipt


def inputs(task, base, *, _session=None):
    config, cp, files, tools, artifacts, physics_path, *_ = _configuration(task, base, _session=_session)
    transport = config["runtime"]["transport"]
    runtime_inputs = [*tools.values(), *artifacts] if transport["kind"] == "local" else [_pin(transport[k], cp.parent, executable=k == "executable", _session=_session) for k in ("executable", "image_archive", "image_manifest")]
    version_source = _pin(config["runtime"]["version_proof"]["source"], cp.parent, _session=_session)
    implementation = []
    if config["schema_version"] == 3:
        from ravel.physics import combine_derivatives, native_likelihood_derivatives
        from ravel.workflow.science import regular
        implementation = [regular(Path(p), base, _session=_session) for p in
            (__file__, combine_derivatives.__file__, native_likelihood_derivatives.__file__)]
        if "fixed_state_observer" in config:
            from ravel.physics import regional_fixed_state
            implementation.append(regular(Path(regional_fixed_state.__file__), base, _session=_session))
    if "source_graph" in config["model"]:
        from ravel.physics import native_statistical_construction as graph
        document = _session.read_document(physics_path) if _session is not None else read_json(physics_path)
        implementation += graph.source_inputs(document, physics_path.parent, _session=_session)
        from ravel.physics import regional_expected
        from ravel.workflow.science import regular
        implementation += [regular(Path(p),base,_session=_session)for p in (__file__,regional_expected.__file__)]
    if "construction" in config["model"]:
        from ravel.physics import statistical_construction as regional
        from ravel.workflow.science import regular
        document = _session.read_document(physics_path) if _session is not None else read_json(physics_path)
        implementation += regional.source_inputs(document, physics_path.parent, _session=_session)
        implementation += [regular(Path(p), base, _session=_session) for p in (__file__, regional.__file__, regional.parametric_shapes.__file__)]
        if any(t.get("shape",{}).get("kind") == regional.continuous_dijet_shapes.KIND for t in document["terms"]):
            implementation.append(regular(Path(regional.continuous_dijet_shapes.__file__),base,_session=_session))
        if "expected_data" in config:
            from ravel.physics import regional_expected
            implementation.append(regular(Path(regional_expected.__file__),base,_session=_session))
    if "calibration" in config:
        from ravel.physics import regional_expected, regional_calibration
        from ravel.workflow.science import regular
        implementation += [regular(Path(p), base, _session=_session) for p in (regional_expected.__file__, regional_calibration.__file__)]
        if "source_graph" in config["model"]:
            from ravel.physics import source_graph_calibration,combine_derivatives
            implementation += [regular(Path(p),base,_session=_session) for p in (source_graph_calibration.__file__,combine_derivatives.__file__)]
            from ravel.physics import ma5_saf
            implementation += [regular(Path(p),base,_session=_session)for p in (ma5_saf.__file__,ma5_saf.reader.__file__)]
        else:implementation += [regular(p, base, _session=_session) for p in regional_calibration.shape_source_paths(document)]
    if "discovery_diagnostic" in config:
        from ravel.physics import discovery_heldout, combine_derivatives
        from ravel.workflow.science import regular
        implementation += [regular(Path(p),base,_session=_session) for p in (discovery_heldout.__file__,combine_derivatives.__file__)]
    return list(dict.fromkeys([cp, *files.values(), *runtime_inputs, version_source, *([physics_path] if physics_path else []), *implementation]))


def execution_seconds(task, base, *, _session=None):
    """Read-only native ceiling for the outer approved scientific-study budget."""
    return _configuration(task, base, _session=_session)[0]["max_seconds"]


def _validation_inputs(task, base, session):
    """Share bound pin digests only inside an existing admission observation."""
    return inputs(task, base, _session=session)


def _validation_execution_seconds(task, base, session):
    """Recheck the complete configuration and budget in that same observation."""
    return execution_seconds(task, base, _session=session)


def commands(config, tools, work, *, has_response=False):
    """Closed command recipe; no arbitrary options or shell evaluation."""
    fit = config["fit"]
    card = work / config["model"]["card"]
    workspace = work / "ravel_workspace.root"
    build = [str(tools["text2workspace"]), str(card), "-o", str(workspace), "-m", str(fit["mass"])]
    if has_response:
        build += ["-P", "ravel_source_response:model"]
    if config["schema_version"] == 3 or "calibration" in config or "discovery_diagnostic" in config:
        return build, None
    if "expected_data" in config:workspace=work/"ravel_expected_workspace.root"
    fit_command = [str(tools["combine"]), str(workspace), "-M", fit["method"], "-m", str(fit["mass"]),
                   "-n", ".ravel", "-s", str(fit["seed"]), "--cl", "0.95",
                   "--redefineSignalPOIs", fit["poi"], "--setParameterRanges",
                   fit["poi"] + "=" + ",".join(str(float(eft.rational(p))) for p in fit["domain"])]
    if fit["method"] == "MultiDimFit":
        if config["schema_version"] == 2:
            _validate_saved_fit({**fit,'data':'observed'} if 'source_graph'in config['model']and 'expected_data'in config else fit)
            fit_command += ["--algo", "none", "-P", fit["poi"], "--saveNLL", "--saveFitResult", "--saveWorkspace", "--saveSpecifiedNuis", "all"]
        else:
            fit_command += ["--algo", "grid", "--points", str(fit["points"]), "-P", fit["poi"], "--saveNLL", "--saveFitResult", "--saveWorkspace"]
    if "absolute_nll" in fit:
        _validate_absolute_scan(config)
        fit_command += ["--saveSpecifiedNuis", "all", "--saveSpecifiedFunc",
                        ",".join("ravel_mean_"+str(i) for i in range(len(config["model"]["regions"]))),
                        "--X-rtd", "REMOVE_CONSTANT_ZERO_POINT=1"]
    if "expected_data" in config and 'source_graph'not in config['model']:
        fit_command += ["--run","blind","--picky","--strictBounds","--rule","CLs","--qtilde","1","--newExpected","1","--saveWorkspace"]
    elif fit["data"] == "asimov_background":
        fit_command += ["-t", "-1", "--expectSignal", "0"]
    if fit["minimizer"] is not None:
        fit_command += ["--cminDefaultMinimizerType", "Minuit2", "--cminDefaultMinimizerAlgo", "Migrad",
                        "--cminDefaultMinimizerStrategy", str(fit["minimizer"]["strategy"]),
                        "--cminDefaultMinimizerTolerance", str(fit["minimizer"]["tolerance"])]
    return build, fit_command



def _validate_absolute_scan(config):
    fit = config["fit"]
    if (config["schema_version"] != 1 or fit.get("absolute_nll") is not True
        or fit["method"] != "MultiDimFit" or fit["data"] != "observed"
        or config["runtime"]["expected"]["combine_version"] != "9.2.1"
        or "construction" not in config["model"]):
        raise ValueError("absolute comparison requires the closed observed Combine 9.2.1 regional grid route")


def _absolute_profile_rows(rows):
    """Exact arithmetic on returned binary64 terms, not an accuracy certificate.

    Combine 9.2.1 documents deltaNLL+nll+nll0 with saveNLL and
    REMOVE_CONSTANT_ZERO_POINT=1. Native deltaNLL itself is stored as float;
    summing its returned representation cannot recover unrecorded precision.
    """
    from fractions import Fraction
    answer=[]
    for i,row in enumerate(rows):
        if not {"deltaNLL","nll","nll0"} <= set(row):
            raise ValueError("native absolute NLL comparison lacks all three original terms")
        terms={key:row[key] for key in ("deltaNLL","nll","nll0")}
        if any(type(v) not in (float,int) or not math.isfinite(v) for v in terms.values()):
            raise ValueError("nonfinite native absolute NLL term")
        answer.append({"row_index":i,"terms":terms,
                       "returned_sum_rational":str(sum((Fraction(v) for v in terms.values()),Fraction(0))),
                       "native_accuracy_qualified":False})
    return answer


def extract_rows(rows, fit):
    """Validate literal limit-tree rows without collapsing profile branches."""
    if not isinstance(rows, list) or not rows or len(rows) > 100005:
        raise ValueError("nonempty bounded native limit tree required")
    for row in rows:
        if not isinstance(row, dict) or any(type(v) not in (int, float) or not math.isfinite(v) for v in row.values()):
            raise ValueError("nonfinite or nonnumeric native tree row")
    if "saved_fit" in fit:
        _validate_saved_fit(fit)
        return _extract_saved_fit_row(rows, fit)
    if fit["method"] == "AsymptoticLimits":
        targets = [(0.025, "minus2sigma"), (0.16, "minus1sigma"), (0.5, "median"), (0.84, "plus1sigma"), (0.975, "plus2sigma")]
        if fit["data"] == "observed":
            targets.append((-1, "observed"))
        values = {}
        for row in rows:
            if not {"limit", "quantileExpected"} <= set(row) or row["limit"] <= 0:
                raise ValueError("positive limit and quantileExpected required")
            matches = [name for quantile, name in targets if abs(row["quantileExpected"] - quantile) <= 1e-5]
            if len(matches) != 1 or matches[0] in values:
                raise ValueError("unexpected or duplicate native quantile")
            values[matches[0]] = row["limit"]
        if len(values) != len(targets):
            raise ValueError("native quantile coverage incomplete")
        expected = [values[name] for _, name in targets if name != "observed"]
        if expected != sorted(expected):
            raise ValueError("expected native quantiles are out of order")
        reference = fit["reference_quantiles"]
        comparisons = []
        if reference is not None:
            for name, value in reference["values"].items():
                difference = values[name] - value
                tolerance = reference["absolute_tolerance"] + reference["relative_tolerance"] * abs(value)
                comparisons.append({"name": name, "actual": values[name], "reference": value,
                                    "difference": difference, "absolute_difference": abs(difference),
                                    "relative_difference": difference / value,
                                    "absolute_relative_difference": abs(difference) / value,
                                    "tolerance": tolerance, "passed": abs(difference) <= tolerance})
        return {"kind": "95_percent_CLs_asymptotic_limits", "quantiles": values, "reference_comparisons": comparisons,
                "passed": all(c["passed"] for c in comparisons), "rows": rows}
    points = []
    lower, upper = [float(eft.rational(p)) for p in fit["domain"]]
    spacing = (upper - lower) / fit["points"]
    tolerance = min(spacing / 4, 1e-6 * max(1.0, abs(lower), abs(upper)))
    grid, best = {}, []
    for row in rows:
        if not {fit["poi"], "deltaNLL", "quantileExpected"} <= set(row):
            raise ValueError("profile tree lacks its declared coefficient, deltaNLL or quantileExpected")
        value = row[fit["poi"]]
        if value < lower - tolerance or value > upper + tolerance:
            raise ValueError("native profile point outside declared signed domain")
        points.append(value)
        if abs(row["quantileExpected"] + 1) <= 1e-5:
            best.append(row)
            continue
        if not 0 <= row["quantileExpected"] <= 1:
            raise ValueError("native profile has an unexpected point quantile identity")
        index = round((value - lower) / spacing - .5)
        expected = lower + (index + .5) * spacing
        if not 0 <= index < fit["points"] or abs(value - expected) > tolerance or index in grid:
            raise ValueError("native profile grid coordinate coverage mismatch or duplicate")
        grid[index] = {"actual": value, "expected": expected, "tolerance": tolerance}
    if len(best) != 1 or set(grid) != set(range(fit["points"])):
        raise ValueError("native profile best-fit identity or grid point coverage incomplete")
    suspect = [i for i, row in enumerate(rows) if row["deltaNLL"] < -1e-6 or row["deltaNLL"] >= 999 or
               any(row.get(key, 0) != 0 for key in ("fit_status", "fitStatus", "status"))]
    absolute = _absolute_profile_rows(rows) if fit.get("absolute_nll") is True else None
    return {**({"absolute_nll_rows": absolute} if absolute is not None else {}),
            "kind": "native_profile_likelihood_scan", "poi": fit["poi"], "rows": rows,
            "passed": not suspect, "suspect_fit_rows": suspect,
            "grid_coverage": {"source_rule": "Combine default one-dimensional bin-center grid, alignEdges=false; best-fit quantile -1 is excluded from grid coverage", "witnesses": grid},
            "scope": "All finite native profile rows retained, including best-fit and multiple branches; no monotonic interval or coverage certification"}


# Executed by the declared native Python only inside the admitted attempt.
NATIVE_PROBE = '''import json, os, platform, sys
import hashlib
import ROOT
from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel
ROOT.gROOT.SetBatch(True)
cfg=json.load(open(sys.argv[1]))
def file_hash(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''): h.update(chunk)
    return h.hexdigest()
runtime_files=[*cfg['runtime']['tools'].values(),*cfg['runtime']['artifacts']]
observed_files={pin['path']:file_hash(pin['path']) for pin in runtime_files}
for artifact in cfg['runtime']['artifacts']:
    if os.path.basename(artifact['path']) in ('libHiggsAnalysisCombinedLimit.so','libHiggsAnalysisCombinedLimit.dylib') or ('source_graph' in cfg['model'] and artifact['path'].endswith(('.so','.dylib'))):
        if ROOT.gSystem.Load(artifact['path']) < 0: raise RuntimeError('pinned Combine custom-class library failed to load')
def names(collection):
    return [item.GetName() for item in collection] if collection else []
def regional_linkage(w, mc, response):
    # Read the actual product factors and server graph; source labels alone do
    # not establish that a count participates in this ModelConfig likelihood.
    def servers(obj):
        it=obj.serverIterator(); values=[]
        while True:
            item=it.Next()
            if not item: break
            values.append(str(item.GetName()))
            if len(values)>4096: raise RuntimeError('regional server census exceeds bound')
        return values
    def node(obj):
        result={'name':str(obj.GetName()),'class':str(obj.ClassName()),'servers':servers(obj)}
        if result['class'] in ('RooGaussian','SimpleGaussianConstraint','RooPoisson'):
            # ROOT 6.22 RooGaussian/RooPoisson advertise proxy x as code 1
            # and mean as code 2. This only matches names into a temporary
            # RooArgSet; do not evaluate analyticalIntegral or infer semantics
            # from the mutable RooAbsArg server-list order.
            gaussian=result['class'] in ('RooGaussian','SimpleGaussianConstraint')
            expected_codes={0:'sigma',1:'x',2:'mean'} if gaussian else {1:'x',2:'mean'}
            refs=result['servers']; roles={}; queries=[]
            if len(refs)!=len(expected_codes) or len(set(refs))!=len(refs):
                raise RuntimeError('regional semantic proxy server population differs')
            for name in refs:
                arg=w.arg(name)
                if not arg: raise RuntimeError('regional semantic proxy server absent')
                requested=ROOT.RooArgSet(arg); selected=ROOT.RooArgSet()
                code=obj.getAnalyticalIntegral(requested,selected)
                matched=names(selected)
                queries.append({'server':name,'code':code,'selected':matched})
                if type(code) is not int or code not in expected_codes or matched!=([name] if code else []):
                    raise RuntimeError('regional semantic proxy dependency query differs')
                role=expected_codes[code]
                if role in roles: raise RuntimeError('regional semantic proxy role repeated')
                roles[role]=name
            result['proxy_identity']={'method':'ROOT6.22/getAnalyticalIntegral-name-match/v1','roles':roles,'queries':queries}
        return result
    def value(obj):
        v=float(obj.getVal())
        print('RAVEL_REGIONAL_GRAPH_RETURN='+json.dumps({'name':str(obj.GetName()),'value_hex':v.hex()},sort_keys=True),flush=True)
        return v
    leaves=[]; products=[]
    def walk(obj, depth=0):
        if depth>8 or len(products)+len(leaves)>2048: raise RuntimeError('regional product graph exceeds bound')
        if str(obj.ClassName())=='RooProdPdf':
            children=list(obj.pdfList()); products.append({'name':str(obj.GetName()),'factors':names(children)})
            for child in children: walk(child,depth+1)
        else: leaves.append(node(obj))
    walk(mc.GetPdf())
    leaf_nodes={n['name']:n for n in leaves}
    auxiliary_widths={}
    for i in range(len(response['document']['auxiliary']['names'])):
        name='ravel_aux_'+str(i)+'_Pdf'; obj=w.pdf(name)
        if not obj: raise RuntimeError('regional auxiliary factor absent')
        observed=leaf_nodes.get(name)
        if not observed or observed['class'] not in ('RooGaussian','SimpleGaussianConstraint'):
            raise RuntimeError('regional Gaussian factor disconnected or changed')
        sigma=w.arg(observed['proxy_identity']['roles']['sigma'])
        if not sigma: raise RuntimeError('regional Gaussian width absent')
        auxiliary_widths[name]={'name':str(sigma.GetName()),'constant':bool(sigma.isConstant()),'value':value(sigma)}
    domains={}
    for name in response['coordinates']:
        v=w.var(name)
        if not v: raise RuntimeError('regional coordinate absent: '+name)
        domains[name]={'minimum':float(v.getMin()),'maximum':float(v.getMax()),'constant':bool(v.isConstant())}
    rows=[]
    for i,b in enumerate(response['document']['bins']):
        channel=b['id']; pdf=w.pdf('pdf_bin'+channel); mean=w.function('n_exp_bin'+channel)
        full=w.function('n_exp_bin'+channel+'_proc_ravel_full'); dummy=w.var('n_exp_bin'+channel+'_proc_ravel_dummy')
        fn=w.function('ravel_mean_'+str(i))
        if not all((pdf,mean,full,dummy,fn)): raise RuntimeError('regional count graph object absent: '+channel)
        rows.append({'channel':channel,'declared_role':b['role'],'pdf':leaf_nodes.get(str(pdf.GetName())),
                     'pdf_observables':names(pdf.getObservables(mc.GetObservables())),
                     'mean':node(mean),'full_process':node(full),'count_function':str(fn.GetName()),
                     'dummy':{'name':str(dummy.GetName()),'constant':bool(dummy.isConstant()),'value':value(dummy)},
                     'initial_total_mean':value(mean),'initial_count_function':value(fn)})
    return {'representation':'regional_count_product/v1','root':node(mc.GetPdf()),
            'products':products,'leaves':leaves,'rows':rows,'auxiliary_widths':auxiliary_widths,'coordinate_domains':domains,
            'extra_initial_mean_evaluations':2*len(rows),'constant_width_reads':len(auxiliary_widths),'constant_dummy_reads':len(rows),
            'semantic_proxy_queries':sum(len(n.get('proxy_identity',{}).get('queries',[])) for n in leaves),
            'scope':'actual count/product/server linkage and initial mean equality; source-bound construction, not arbitrary graph equivalence'}

classes={name:bool(ROOT.TClass.GetClass(name)) for name in cfg['runtime']['expected']['custom_classes']}
result={'architecture':platform.machine(),'root_version':ROOT.gROOT.GetVersion(),
        'cmssw_version':os.environ.get('CMSSW_VERSION'),'custom_classes':classes,
        'observed_runtime_files':observed_files,
        'combine_python_module':sys.modules[PhysicsModel.__module__].__file__}
if len(sys.argv)>2:
    f=ROOT.TFile.Open(sys.argv[2]); w=f.Get('w') if f else None
    if not w: raise RuntimeError('workspace w absent')
    mc=w.obj('ModelConfig'); data=w.data('data_obs')
    if not mc or not data or not mc.GetPdf(): raise RuntimeError('native ModelConfig/pdf/data absent')
    poi=w.var(cfg['fit']['poi'])
    if not poi: raise RuntimeError('declared POI absent')
    derivative_state=None
    graph_diagnostics=cfg['schema_version']==3 and 'source_graph' in cfg['model']
    diagnostic_action=len(sys.argv)==5 and sys.argv[4]=='--diagnose-source-graph'
    if len(sys.argv)>4 and sys.argv[4]=='--diagnose-source-graph' and (not graph_diagnostics or not diagnostic_action):
        raise RuntimeError('unknown source graph diagnostic action')
    derivative_action=cfg['schema_version']==3 and (not graph_diagnostics or diagnostic_action)
    if derivative_action:
        import importlib.util
        from pathlib import Path
        root=Path(__file__).resolve().parent
        context=json.load(open(root/'ravel_derivative_context.json'))
        if file_hash(sys.argv[2])!=context['definition']['workspace_sha256']: raise RuntimeError('derivative workspace bytes differ')
        staged=context['definition']['staged_implementation']
        modules={}
        module_names=[('kernel','ravel_derivative_kernel.py'),('consumer','ravel_combine_derivatives.py')]
        if 'fixed_state_observer' in cfg: module_names.append(('fixed_observer','ravel_regional_fixed_state.py'))
        for key,name in module_names:
            path=root/name
            if file_hash(path)!=staged[name]: raise RuntimeError('staged derivative implementation differs')
            spec=importlib.util.spec_from_file_location('ravel_bound_'+key,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules[key]=module
        if file_hash(__file__)!=context['definition']['worker_sha256']: raise RuntimeError('derivative native worker differs')
        if ROOT.gROOT.GetVersion()!=context['definition']['native_root_version']: raise RuntimeError('derivative actual ROOT version differs from admitted source policy')
        derivative_state=modules['consumer'].capture(w,mc)
    cat=w.cat('CMS_channel')
    channels=[]
    if cat:
        if cfg['schema_version']==3:
            channels=[str(cat.getOrdinal(i).first) for i in range(cat.numTypes())]
        else:
            for i in range(cat.numTypes()):
                cat.setIndex(i); channels.append(cat.getLabel())
    elif len(cfg['model']['regions'])==1 and 'construction' not in cfg['model'] and 'source_graph' not in cfg['model']:
        channels=[cfg['model']['regions'][0]['channel']]
    result['workspace']={'pois':names(mc.GetParametersOfInterest()),'nuisances':names(mc.GetNuisanceParameters()),
        'global_observables':names(mc.GetGlobalObservables()),'observables':names(mc.GetObservables()),
        'channels':channels,'data_entries':int(data.numEntries()),'poi_domain':[poi.getMin(),poi.getMax()]}
    opts=[]
    if mc.GetNuisanceParameters(): opts.append(ROOT.RooFit.Constrain(mc.GetNuisanceParameters()))
    if mc.GetGlobalObservables(): opts.append(ROOT.RooFit.GlobalObservables(mc.GetGlobalObservables()))
    # Combine's derived RooSimultaneousOpt exposes the virtual linked-list
    # overload. Keep the RooCmdArgs alive and pass the same options explicitly.
    cmdlist=ROOT.RooLinkedList()
    for option in opts: cmdlist.Add(option)
    nll=mc.GetPdf().createNLL(data,cmdlist)
    response=json.load(open(sys.argv[3])) if len(sys.argv)>3 else None
    if response and response.get('kind') in ('regional-poisson-construction/v1','native-source-graph/v1'):
        if data.numEntries()!=1: raise RuntimeError('constructed counting data requires one full-vector entry')
        observed=data.get(0)
        counts={}
        for row in response['document']['bins']:
            var=observed.find('n_obs_bin'+row['id'])
            if not var: raise RuntimeError('constructed observation absent: '+row['id'])
            counts[row['id']]=float(var.getVal())
        globals_={}
        for i in range(len(response['document']['auxiliary']['names'])):
            name='ravel_aux_'+str(i)+'_In';var=w.var(name)
            if not var: raise RuntimeError('constructed auxiliary observation absent')
            globals_[name]={'value':float(var.getVal()),'constant':bool(var.isConstant())}
        result['construction_observations']={'counts':counts,'dataset_weight':float(data.weight()),'auxiliary':globals_}
        result['construction_linkage']=regional_linkage(w,mc,response)
        result['construction_global_ranges']={name:{'has_min':bool(w.var(name).hasMin()),'has_max':bool(w.var(name).hasMax())} for name in globals_}
    if response and response.get('kind')=='native-source-graph/v1':
        cell=next(c for c in response['recipe']['cells'] if c['id']==response['cell'])
        result['source_graph_nodes']={}
        result['source_graph_observables']={}
        import importlib.util
        from pathlib import Path
        graph_helper=Path(__file__).resolve().parent/'ravel_regional_expected.py'
        if file_hash(graph_helper)!=cfg['graph_observer_implementation_sha256']:raise RuntimeError('source graph observer changed')
        graph_spec=importlib.util.spec_from_file_location('ravel_graph_observer',graph_helper)
        graph_observer=importlib.util.module_from_spec(graph_spec);graph_spec.loader.exec_module(graph_observer)
        result['source_graph_templates']={}
        result['construction_count_domains']={}
        for b in response['document']['bins']:
            var=w.var('n_obs_bin'+b['id'])
            result['construction_count_domains'][b['id']]={'has_min':bool(var.hasMin()),'has_max':bool(var.hasMax()),'minimum':float(var.getMin())if var.hasMin()else None,'maximum':float(var.getMax())if var.hasMax()else None}
        for observable in cell['observables']:
            var=w.var(observable['name'])
            if not var: raise RuntimeError('original source integration observable absent')
            result['source_graph_observables'][observable['name']]={'bounds':[float(var.getMin()),float(var.getMax())],'unit':str(var.getUnit()),'constant':bool(var.isConstant())}
        for node in cell['nodes']:
            obj=w.arg(node['name'])
            if not obj: raise RuntimeError('original source graph node absent')
            result['source_graph_nodes'][node['name']]={'class':str(obj.ClassName()),'servers':[]}
            iterator=obj.serverIterator()
            while True:
                server=iterator.Next()
                if not server: break
                result['source_graph_nodes'][node['name']]['servers'].append(str(server.GetName()))
                if len(result['source_graph_nodes'][node['name']]['servers'])>4096: raise RuntimeError('source graph server bound exceeded')
            result['source_graph_nodes'][node['name']]['servers'].sort()
            if node['kind']=='template':
                table=obj.dataHist();t=node['template'];axes=t.get('axes',[{'observable':t['observable'],'edges':t['edges']}]if 'observable'in t else None)
                rows=[];actual_axes=[]
                for axis in axes:
                    var=table.get(0).find(axis['observable']);binning=var.getBinning()
                    actual_axes.append({'observable':axis['observable'],'edges':[float(binning.binLow(i))for i in range(binning.numBins())]+[float(binning.binHigh(binning.numBins()-1))]})
                for i in range(table.numEntries()):
                    row=table.get(i);indices=[int(row.find(a['observable']).getBinning().binNumber(row.find(a['observable']).getVal()))for a in axes]
                    rows.append({'indices':indices,'height':float(table.weight()),'sumw2':float(table.get_sumw2(i))})
                result['source_graph_templates'][node['name']]={'axes':actual_axes,'cells':rows,'interpolation_order':int(obj.getInterpolationOrder())}
        result['source_graph_integrals']=graph_observer.source_graph_integrals(w,response)
        if file_hash(graph_helper)!=cfg['graph_observer_implementation_sha256']:raise RuntimeError('source graph observer changed while reading')
            
    from fractions import Fraction
    initial=poi.getVal(); witnesses=[]
    for point in cfg['fit']['fixed_witness_points']:
        from fractions import Fraction
        poi.setVal(float(Fraction(point)))
        scales={}
        if response:
            for name in response['functions']:
                fn=w.function(name)
                if not fn: raise RuntimeError('native response absent: '+name)
                scales[name]=float(fn.getVal())
        row={'point':str(point),'raw_nll_at_source_nuisance_values':float(nll.getVal()),'scales':scales}
        if response and response.get('kind') in ('regional-poisson-construction/v1','native-source-graph/v1'):
            state={}
            for name in response['coordinates']:
                var=w.var(name)
                if not var: raise RuntimeError('constructed coordinate absent: '+name)
                state[name]={'value':float(var.getVal()),'minimum':float(var.getMin()),'maximum':float(var.getMax()),'constant':bool(var.isConstant())}
            row['construction_state']=state
        if response and response.get('kind')=='native-source-graph/v1':row['source_graph_integrals']=graph_observer.source_graph_integrals(w,response)
        witnesses.append(row)
    poi.setVal(initial)
    result['fixed_witnesses']=witnesses
    if len(sys.argv)>4 and sys.argv[4] not in ('--calibrate','--diagnose-source-graph','--discovery'):
        if sys.argv[4] not in ('--prepare-expected','--qualify-expected') or 'expected_data' not in cfg: raise RuntimeError('unknown native preparation action')
        import importlib.util
        from pathlib import Path
        root=Path(__file__).resolve().parent
        path=root/'ravel_regional_expected.py'
        if file_hash(path)!=cfg['expected_implementation_sha256']:raise RuntimeError('expected helper source changed')
        spec=importlib.util.spec_from_file_location('ravel_expected',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if sys.argv[4]=='--prepare-expected':
            result['expected_preparation']=(module.prepare_source_graph if response.get('kind')=='native-source-graph/v1'else module.prepare)(ROOT,w,mc,data,nll,response,root/'ravel_expected_preparation.json')
            target=root/'ravel_expected_workspace.root'
            if target.exists():raise RuntimeError('expected workspace path already exists')
            w.writeToFile(str(target))
        else:
            if response.get('kind')=='native-source-graph/v1':raise RuntimeError('generic source graph has no admitted asymptotic crossing law')
            request_path=root/'ravel_expected_crossing_request.json'
            if len(sys.argv)!=6 or file_hash(request_path)!=sys.argv[5]:raise RuntimeError('crossing request bytes differ')
            request=json.load(open(request_path))
            if request['fit']!=cfg['fit']:raise RuntimeError('crossing fit contract changed')
            result['expected_crossings']=module.qualify_crossings(ROOT,w,mc,data,nll,response,request,root/'ravel_expected_crossings.json')
            if file_hash(request_path)!=sys.argv[5]:raise RuntimeError('crossing request changed during native profiling')
        if file_hash(path)!=cfg['expected_implementation_sha256']:raise RuntimeError('expected helper changed during native preparation')
    if len(sys.argv)>4 and sys.argv[4]=='--discovery':
        if len(sys.argv)!=6 or 'discovery_diagnostic' not in cfg or not response or response.get('kind')!='native-source-graph/v1':raise RuntimeError('unknown discovery action')
        import importlib.util
        from pathlib import Path
        root=Path(__file__).resolve().parent;helpers={}
        source_helpers=[('optimizer','ravel_regional_expected.py','expected_implementation_sha256'),
            ('discovery','ravel_discovery_heldout.py','discovery_implementation_sha256'),
            ('graph_state','ravel_graph_state.py','discovery_state_implementation_sha256')]
        for key,name,pin in source_helpers:
            path=root/name
            if file_hash(path)!=cfg[pin]:raise RuntimeError('discovery helper source changed')
            spec=importlib.util.spec_from_file_location('ravel_bound_'+key,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);helpers[key]=module
        remaining=float(sys.argv[5])
        if not 0<remaining<=cfg['max_seconds']:raise RuntimeError('discovery remaining budget differs')
        preparation=json.load(open(root/'ravel_expected_preparation.json'))
        result['discovery']=helpers['discovery'].execute(ROOT,w,mc,data,nll,response,cfg['discovery_diagnostic'],
            preparation,root/'ravel_discovery_heldout_journal.json',helpers['optimizer'],helpers['graph_state'],remaining)
        for key,name,pin in source_helpers:
            if file_hash(root/name)!=cfg[pin]:raise RuntimeError('discovery helper changed during execution')
    if len(sys.argv)>4 and sys.argv[4]=='--calibrate':
        if len(sys.argv)!=6 or 'calibration' not in cfg or not response or response.get('kind')not in ('regional-poisson-construction/v1','native-source-graph/v1'):raise RuntimeError('unknown calibration action')
        import importlib.util
        from pathlib import Path
        root=Path(__file__).resolve().parent
        helpers={}
        for key,name,pin in [('optimizer','ravel_regional_expected.py','calibration_optimizer_sha256'),('calibration','ravel_regional_calibration.py','calibration_implementation_sha256')]:
            path=root/name
            if file_hash(path)!=cfg[pin]:raise RuntimeError('calibration helper source changed')
            spec=importlib.util.spec_from_file_location('ravel_bound_'+key,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);helpers[key]=module
        graph_calibration=response.get('kind')=='native-source-graph/v1'
        has_shapes=not graph_calibration and any('shape' in term for term in response['document']['terms'])
        if has_shapes!=('calibration_shape_sources' in cfg):raise RuntimeError('calibration shape source binding differs')
        if has_shapes:helpers['calibration'].bind_shape_sources(root,cfg['calibration_shape_sources'])
        remaining=float(sys.argv[5])
        if not 0<remaining<=cfg['max_seconds']:raise RuntimeError('calibration remaining budget differs')
        graph_law=None
        if graph_calibration:
            for key,name,pin in [('graph_calibration','ravel_source_graph_calibration.py','graph_calibration_implementation_sha256'),('graph_state','ravel_graph_state.py','graph_state_implementation_sha256')]:
                path=root/name
                if file_hash(path)!=cfg[pin]:raise RuntimeError('graph calibration helper source changed')
                spec=importlib.util.spec_from_file_location('ravel_bound_'+key,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);helpers[key]=module
            graph_law=helpers['graph_calibration'].GraphLaw(ROOT,w,mc,response,cfg['calibration'],helpers['optimizer'],helpers['calibration'],helpers['graph_state'])
        result['calibration']=helpers['calibration'].execute(ROOT,w,mc,data,response,cfg['calibration'],helpers['optimizer'],root/'ravel_calibration_journal.json',remaining,_graph_law=graph_law)
        if graph_calibration:
            for name,pin in [('ravel_source_graph_calibration.py','graph_calibration_implementation_sha256'),('ravel_graph_state.py','graph_state_implementation_sha256')]:
                if file_hash(root/name)!=cfg[pin]:raise RuntimeError('graph calibration helper changed during execution')
        for key,name,pin in [('optimizer','ravel_regional_expected.py','calibration_optimizer_sha256'),('calibration','ravel_regional_calibration.py','calibration_implementation_sha256')]:
            if file_hash(root/name)!=cfg[pin]:raise RuntimeError('calibration helper changed during profiling')
        if has_shapes:helpers['calibration'].check_shape_sources(root,cfg['calibration_shape_sources'])
    if derivative_action:
        recorder=modules['consumer'].JsonlRecorder(root/'ravel_derivative_points.jsonl')
        try:
            result['derivatives']=modules['consumer'].execute(w,mc,data,nll,cfg['derivatives'],context,
                {'name':cfg['fit']['poi'],'bounds':[float(Fraction(p)) for p in cfg['fit']['domain']]},
                modules['kernel'],initial_state=derivative_state,recorder=recorder)
        finally:
            recorder.close()
        if 'fixed_state_observer' in cfg:
            observer_recorder=modules['consumer'].JsonlRecorder(root/'ravel_fixed_state_points.jsonl')
            try:
                result['fixed_state_observer']=modules['fixed_observer'].execute(w,mc,data,nll,cfg['fixed_state_observer'],response,
                    modules['consumer'],lambda axis: ROOT.RooArgSet(axis),recorder=observer_recorder)
            finally:
                observer_recorder.close()
        for name,expected in staged.items():
            if file_hash(root/name)!=expected: raise RuntimeError('staged derivative implementation changed')
        if file_hash(sys.argv[2])!=context['definition']['workspace_sha256'] or file_hash(__file__)!=context['definition']['worker_sha256']: raise RuntimeError('derivative workspace/worker changed')
    f.Close()
print('RAVEL_NATIVE_PROBE='+json.dumps(result,allow_nan=False,sort_keys=True))
'''

# Extraction uses the same pinned ROOT worker, so the host needs no ROOT reader.
NATIVE_RESULT = '''import json, sys
import ROOT
ROOT.gROOT.SetBatch(True)
cfg=json.load(open(sys.argv[2]))
for pin in cfg['runtime']['artifacts']:
    if pin['path'].endswith(('libHiggsAnalysisCombinedLimit.so','libHiggsAnalysisCombinedLimit.dylib')):
        if ROOT.gSystem.Load(pin['path'])<0: raise RuntimeError('pinned result custom-class library failed to load')
f=ROOT.TFile.Open(sys.argv[1])
if not f or f.IsZombie(): raise RuntimeError('native result ROOT file unreadable')
tree=f.Get('limit')
if not tree or not tree.InheritsFrom('TTree'): raise RuntimeError('native result lacks limit TTree')
if not 0 < tree.GetEntries() <= 100005: raise RuntimeError('native result row bound exceeded')
integers={'Bool_t','Char_t','UChar_t','Short_t','UShort_t','Int_t','UInt_t','Long_t','ULong_t','Long64_t','ULong64_t'}
numeric=integers|{'Float_t','Double_t','Float16_t','Double32_t'}
leaves=[leaf for leaf in tree.GetListOfLeaves() if leaf.GetTypeName() in numeric and leaf.GetLenStatic()==1 and not leaf.GetLeafCount()]
rows=[]
for i in range(int(tree.GetEntries())):
    if tree.GetEntry(i)<=0: raise RuntimeError('native result row unreadable')
    rows.append({leaf.GetName():(int(leaf.GetValueLong64()) if leaf.GetTypeName() in integers else float(leaf.GetValue())) for leaf in leaves})
diagnostics=[]
def visit(directory,prefix=''):
    for key in directory.GetListOfKeys():
        name=prefix+key.GetName(); cls=ROOT.TClass.GetClass(key.GetClassName())
        if cls and cls.InheritsFrom('TDirectory'): visit(key.ReadObj(),name+'/')
        elif cls and cls.InheritsFrom('RooFitResult'):
            obj=key.ReadObj()
            diagnostics.append({'name':name,'status':int(obj.status()),'covariance_quality':int(obj.covQual()),
                'edm':float(obj.edm()),'minimum_nll':float(obj.minNll()),
                'invalid_nll_evaluations':int(obj.numInvalidNLL()),
                'status_history':[{'label':str(obj.statusLabelHistory(i)),'status':int(obj.statusCodeHistory(i))} for i in range(obj.numStatusHistory())]})
            if cfg['schema_version']==2:
                last=diagnostics[-1]
                floating=obj.floatParsFinal(); constants=obj.constPars()
                if not 0 < floating.getSize() <= 10000 or constants.getSize()>10000: raise RuntimeError('saved parameter population bound exceeded')
                last['floating_parameters']=[{'name':str(floating.at(i).GetName()),'value':float(floating.at(i).getVal()),'error':float(floating.at(i).getError())} for i in range(floating.getSize())]
                last['constant_parameters']=[{'name':str(constants.at(i).GetName()),'value':float(constants.at(i).getVal())} for i in range(constants.getSize())]
visit(f)
for path in sys.argv[3:]:
    other=ROOT.TFile.Open(path)
    if not other or other.IsZombie(): raise RuntimeError('native diagnostic ROOT file unreadable')
    visit(other,path.split('/')[-1]+':')
    other.Close()
print('RAVEL_NATIVE_RESULT='+json.dumps({'rows':rows,'fit_results':diagnostics},allow_nan=False,sort_keys=True))
f.Close()
'''


def extract_native_result(log, fit):
    values = [line.split("=", 1)[1] for line in log.splitlines() if line.startswith("RAVEL_NATIVE_RESULT=")]
    if len(values) != 1:
        raise ValueError("native result probe must produce exactly one structured output")
    result = json.loads(values[0], parse_constant=lambda s: (_ for _ in ()).throw(ValueError("nonfinite native result")))
    _keys(result, {"rows", "fit_results"}, "native output probe")
    if not isinstance(result["fit_results"], list):
        raise ValueError("native fit diagnostic list required")
    inference = extract_rows(result["rows"], fit)
    diagnostics = result["fit_results"]
    if "saved_fit" in fit:
        return _extract_saved_diagnostics(inference, diagnostics, fit)
    suspect = []
    for row in diagnostics:
        _keys(row, {"name", "status", "covariance_quality", "edm", "minimum_nll", "invalid_nll_evaluations", "status_history"}, "RooFitResult diagnostic")
        if not isinstance(row["name"], str) or not row["name"] or any(type(row[k]) is not int for k in ("status", "covariance_quality", "invalid_nll_evaluations")) or not isinstance(row["status_history"], list):
            raise ValueError("malformed RooFitResult diagnostic")
        _finite(row["minimum_nll"], "fitted minimum NLL")
        if _finite(row["edm"], "fit EDM") < 0 or row["status"] != 0 or row["covariance_quality"] < 2:
            suspect.append(row["name"])
    inference["fit_diagnostics"] = {"saved_fit_results": diagnostics, "suspect_results": suspect,
        "saved_result_available": bool(diagnostics),
        "scope": "Saved fits only; grid-point failures additionally use tree sentinels/status and literal logs. Combine9.2.1 grid does not save RooFitResult despite its saveFitResult flag; AsymptoticLimits need not save one. Absence is explicit and does not establish convergence."}
    inference["passed"] = inference["passed"] and not suspect
    return inference


def container_command(command, directory, environment, transport, out, seconds, cidfile):
    """One immutable-image command with no network, one CPU and bounded lifetime."""
    owner = hashlib.sha256(str(Path(out).absolute()).encode()).hexdigest()[:16]
    native = [str(transport["executable"]["path"]), "--connection", transport["connection"], "run", "--rm",
              "--pull=never", "--platform=linux/amd64", "--network=none", "--cpus=1", "--memory=4g",
              "--user=0",
              "--pids-limit=512", "--timeout", str(seconds), "--stop-timeout=1", "--cidfile", str(cidfile),
              "--label", "ravel.native.owner=" + owner, "--workdir", str(directory),
              "--volume", str(out) + ":" + str(out) + ":rw", "--entrypoint", command[0]]
    for key, value in sorted(environment.items()):
        native += ["--env", key + "=" + value]
    return native + [transport["image_id"], *command[1:]]


def _process(command, directory, environment, log, deadline, *, transport=None, out=None, expected_returncode=0):
    if type(expected_returncode) is not int or expected_returncode not in (0, 234) or expected_returncode != 0 and len(command) != 1:
        raise ValueError("only the no-argument version diagnostic may expect a nonzero exit")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("native calculation exceeded its declared total time budget")
    cidfile = log.with_suffix(".cid")
    native_command = command
    client_environment = environment
    if transport is not None and transport["kind"] == "podman":
        native_command = container_command(command, directory, environment, transport, out, max(1, math.ceil(remaining)), cidfile)
        client_environment = {"LC_ALL": "C", **transport["client_environment"]}
    receipt = {"argv": native_command, "cwd": str(directory), "remaining_seconds": remaining,
               "client_environment": client_environment, "expected_returncode": expected_returncode}
    atomic_json(log.with_suffix(".command.json"), receipt)
    with log.open("wb") as stream:
        process = subprocess.Popen(native_command, cwd=directory, env=client_environment, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            if transport is not None and transport["kind"] == "podman" and cidfile.is_file():
                container = cidfile.read_text().strip()
                if re.fullmatch(r"[a-f0-9]{64}", container):
                    subprocess.run([str(transport["executable"]["path"]), "--connection", transport["connection"], "rm", "--force", container],
                                   env=client_environment, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=10)
            raise ValueError("native command exceeded its declared time budget") from None
    atomic_json(log.with_suffix(".command.json"), {**receipt, "actual_returncode": code})
    if code != expected_returncode:
        raise ValueError("native command failed; retained log " + str(log))
    return log.read_text(errors="replace")



def _probe_result(log):
    values = [line.split("=", 1)[1] for line in log.splitlines() if line.startswith("RAVEL_NATIVE_PROBE=")]
    if len(values) != 1:
        raise ValueError("actual native probe did not produce exactly one structured identity")
    result = json.loads(values[0], parse_constant=lambda s: (_ for _ in ()).throw(ValueError("nonfinite probe")))
    return result


def _check_probe(result, expected, artifacts=None, runtime=None):
    for name in ("architecture", "root_version", "cmssw_version"):
        if result.get(name) != expected[name]:
            raise ValueError("actual native runtime differs from source-compatible expectation: " + name)
    if result.get("custom_classes") != {name: True for name in expected["custom_classes"]}:
        raise ValueError("native custom-class/ABI probe did not qualify all required classes")
    if artifacts is not None:
        module = Path(result.get("combine_python_module", ""))
        if module not in {p for p in artifacts if p.name == "PhysicsModel.py"}:
            raise ValueError("actual imported Combine Python module was not pinned")
    if runtime is not None:
        pins = [*runtime["tools"].values(), *runtime["artifacts"]]
        if result.get("observed_runtime_files") != {pin["path"]: pin["sha256"] for pin in pins}:
            raise ValueError("actual native runtime bytes differ from the approved file pins")


def _check_regional_linkage(probe, config, response):
    """Closed Combine counting representation; never infer coverage from names alone."""
    ws=probe.get('workspace',{}); d=response['document']; bins=d['bins']
    if [p['name'] for p in d['parameters'] if p['role']=='poi'] != [config['fit']['poi']]:
        raise ValueError('regional source and declared POI differ')
    expected_regions=[{'channel':b['id'],'role':b['role']} for b in bins]
    if config['model']['regions'] != expected_regions:
        raise ValueError('regional source and declared channel/role census differ')
    if ws.get('channels') != [] or ws.get('data_entries') != 1:
        raise ValueError('constructed product requires uncategorized full-vector data')
    observations=['n_obs_bin'+b['id'] for b in bins]
    if sorted(ws.get('observables',[])) != sorted(observations):
        raise ValueError('regional observable census differs')
    nuisances={p['name'] for p in d['parameters'] if p['role']!='poi' and not p['fixed']}
    nuisances.update('ravel_aux_'+str(i) for i in range(len(d['auxiliary']['names'])))
    globals_={'ravel_aux_'+str(i)+'_In' for i in range(len(d['auxiliary']['names']))}
    if sorted(ws.get('nuisances',[])) != sorted(nuisances) or sorted(ws.get('global_observables',[])) != sorted(globals_):
        raise ValueError('regional ModelConfig nuisance/global population differs')
    expected_ranges={n:{'has_min':False,'has_max':False} for n in globals_}
    if probe.get('construction_global_ranges') != expected_ranges:
        raise ValueError('regional Gaussian auxiliary observations must have full-real support')
    q=probe.get('construction_linkage')
    if not isinstance(q,dict) or q.get('representation')!='regional_count_product/v1':
        raise ValueError('actual regional count-product graph witness required')
    expected_domains={p['name']:{'minimum':float(eft.rational(p['bounds'][0])),'maximum':float(eft.rational(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
    expected_domains.update({'ravel_aux_'+str(i):{'minimum':float(eft.rational(bounds[0])),'maximum':float(eft.rational(bounds[1])),'constant':False} for i,bounds in enumerate(d['auxiliary']['eta_bounds'])})
    if q.get('coordinate_domains') != expected_domains:
        raise ValueError('regional physical/eta parameter domains or fixed flags changed')
    root=q.get('root',{})
    if root.get('name')!='model_s' or root.get('class')!='RooProdPdf':
        raise ValueError('regional ModelConfig must select model_s RooProdPdf')
    products=q.get('products',[]); leaves=q.get('leaves',[])
    if not isinstance(products,list) or not isinstance(leaves,list) or len(products)+len(leaves)>2048:
        raise ValueError('bounded regional product census required')
    nodes={}
    for n in products+leaves:
        if not isinstance(n,dict) or not isinstance(n.get('name'),str) or n['name'] in nodes:
            raise ValueError('duplicate or invalid regional product/leaf')
        nodes[n['name']]=n
    used=[]
    def visit(name,depth=0):
        if depth>8 or name in used or name not in nodes: raise ValueError('disconnected/duplicate regional factor graph')
        used.append(name); n=nodes[name]
        if 'factors' in n:
            if not isinstance(n['factors'],list) or not n['factors']: raise ValueError('empty product factor list')
            for child in n['factors']: visit(child,depth+1)
    visit('model_s')
    if set(used)!=set(nodes) or sorted(root.get('servers',[]))!=sorted(nodes['model_s'].get('factors',[])):
        raise ValueError('regional factor graph has unaccounted members')
    expected_leaf_names={'pdf_bin'+b['id'] for b in bins}|{'ravel_aux_'+str(i)+'_Pdf' for i in range(len(globals_))}
    if {n['name'] for n in leaves}!=expected_leaf_names:
        raise ValueError('regional count/constraint factors omitted or added')
    if q.get('constant_width_reads')!=len(globals_) or set(q.get('auxiliary_widths',{}))!={'ravel_aux_'+str(i)+'_Pdf' for i in range(len(globals_))}:
        raise ValueError('complete Gaussian width observations required')
    def check_proxy_identity(n, expected_roles, codes):
        servers=n.get('servers',[]); witness=n.get('proxy_identity',{})
        if (not isinstance(servers,list) or len(servers)!=len(expected_roles) or len(set(servers))!=len(servers)
                or set(servers)!=set(expected_roles.values()) or not isinstance(witness,dict)
                or set(witness)!={'method','roles','queries'}
                or witness['method']!='ROOT6.22/getAnalyticalIntegral-name-match/v1'
                or witness['roles']!=expected_roles):
            raise ValueError('regional semantic proxy identities disconnected or changed')
        expected_queries=[{'server':name,'code':codes[name],'selected':[name] if codes[name] else []} for name in servers]
        queries=witness['queries']
        if (not isinstance(queries,list) or queries!=expected_queries
                or any(not isinstance(row,dict) or type(row.get('code')) is not int for row in queries)):
            raise ValueError('regional complete semantic proxy query census differs')
    for i in range(len(globals_)):
        n=nodes['ravel_aux_'+str(i)+'_Pdf']; servers=n.get('servers',[])
        roles={'x':'ravel_aux_'+str(i),'mean':'ravel_aux_'+str(i)+'_In','sigma':q['auxiliary_widths'][n['name']].get('name')}
        if n.get('class') not in ('RooGaussian','SimpleGaussianConstraint') or not isinstance(roles['sigma'],str):
            raise ValueError('regional auxiliary factor disconnected or changed')
        check_proxy_identity(n,roles,{roles['x']:1,roles['mean']:2,roles['sigma']:0})
        if q['auxiliary_widths'][n['name']]!={'name':roles['sigma'],'constant':True,'value':1.0}:
            raise ValueError('regional Gaussian width must remain constant one')
    if type(q.get('semantic_proxy_queries')) is not int or q['semantic_proxy_queries']!=3*len(globals_)+2*len(bins):
        raise ValueError('complete regional semantic proxy query population required')
    rows=q.get('rows',[])
    if not isinstance(rows,list) or len(rows)!=len(bins) or q.get('extra_initial_mean_evaluations')!=2*len(bins) or q.get('constant_dummy_reads')!=len(bins):
        raise ValueError('complete regional count rows and evaluation census required')
    for i,(row,b) in enumerate(zip(rows,bins)):
        c=b['id']; pdf='pdf_bin'+c; mean='n_exp_bin'+c
        full=mean+'_proc_ravel_full';dummy=mean+'_proc_ravel_dummy';fn='ravel_mean_'+str(i)
        observed_pdf=row.get('pdf',{}); roles={'x':'n_obs_bin'+c,'mean':mean}
        if (row.get('channel')!=c or row.get('declared_role')!=b['role'] or observed_pdf!=nodes[pdf]
                or observed_pdf.get('name')!=pdf or observed_pdf.get('class')!='RooPoisson'
                or row.get('pdf_observables')!=['n_obs_bin'+c]):
            raise ValueError('regional Poisson/count/role linkage differs')
        check_proxy_identity(observed_pdf,roles,{roles['x']:1,roles['mean']:2})
        observed_mean=row.get('mean',{})
        if observed_mean.get('name')!=mean or observed_mean.get('class')!='RooAddition' or sorted(observed_mean.get('servers',[]))!=sorted([full,dummy]):
            raise ValueError('regional total mean has altered components')
        if row.get('full_process')!={'name':full,'class':'ProcessNormalization','servers':[fn]} or row.get('count_function')!=fn:
            raise ValueError('regional process lost source count-function linkage')
        if row.get('dummy')!={'name':dummy,'constant':True,'value':0.0}:
            raise ValueError('regional dummy process must remain constant zero')
        actual=_finite(row.get('initial_total_mean'),'regional total mean')
        source=_finite(row.get('initial_count_function'),'regional source mean')
        if actual<=0 or source<=0 or abs(actual-source)>1e-10+1e-8*abs(source):
            raise ValueError('regional total expected count differs from source function')


def _check_workspace(probe, config, response, expected_preparation=None):
    ws = probe.get("workspace", {})
    if ws.get("pois") != [config["fit"]["poi"]]:
        raise ValueError("actual native workspace changed POI or SR/CR channel coverage")
    if response and response.get("kind") in ("regional-poisson-construction/v1", "native-source-graph/v1"):
        _check_regional_linkage(probe, config, response)
    elif set(ws.get("channels", [])) != {r["channel"] for r in config["model"]["regions"]}:
        raise ValueError("actual native workspace changed POI or SR/CR channel coverage")
    if response and ws.get("poi_domain") != [float(eft.rational(p)) for p in config["fit"]["domain"]]:
        raise ValueError("native EFT workspace changed published signed domain")
    witnesses = probe.get("fixed_witnesses", [])
    if [p.get("point") for p in witnesses] != config["fit"]["fixed_witness_points"]:
        raise ValueError("native fixed-witness coverage mismatch")
    if response and response.get("kind") == "regional-poisson-construction/v1":
        observed = probe.get("construction_observations")
        expected = {"counts": {b["id"]: (0 if b["observed"] is None else b["observed"]) for b in response["document"]["bins"]}, "dataset_weight": 1.0,
                    "auxiliary": {"ravel_aux_" + str(i) + "_In": {"value": 0.0, "constant": True} for i in range(len(response["document"]["auxiliary"]["names"]))}}
        if expected_preparation is not None:
            from ravel.physics import regional_expected
            regional_expected.validate_delivery(expected_preparation,response)
            expected=regional_expected.observation_expectation(expected_preparation)
        if observed != expected:
            raise ValueError("constructed native observed counts/weight/auxiliary values differ")
    if response and response.get("kind") == "native-source-graph/v1":
        from ravel.physics import native_statistical_construction as graph
        return graph.structural_witness(probe, config, response, expected_preparation)
    comparisons = []
    for witness in witnesses:
        _finite(witness["raw_nll_at_source_nuisance_values"], "native fixed NLL")
        if response:
            construction = response.get("kind") == "regional-poisson-construction/v1"
            if construction:
                from ravel.physics import statistical_construction as regional
                state = witness.get("construction_state", {})
                if state.get(config["fit"]["poi"], {}).get("value") != float(eft.rational(witness["point"])):
                    raise ValueError("native constructed witness has wrong POI coordinate")
                exact = regional.native_witness(response, state)
                expected_nuisances = {p["name"] for p in response["document"]["parameters"] if p["role"] != "poi" and not p["fixed"]}
                expected_nuisances.update("ravel_aux_" + str(i) for i in range(len(response["document"]["auxiliary"]["names"])))
                if set(ws.get("nuisances", [])) != expected_nuisances:
                    raise ValueError("constructed native nuisance population differs")
                expected_globals = {"ravel_aux_" + str(i) + "_In" for i in range(len(response["document"]["auxiliary"]["names"]))}
                if set(ws.get("global_observables", [])) != expected_globals:
                    raise ValueError("constructed auxiliary observations duplicated/omitted")
            else:
                exact = eft.evaluate(response, witness["point"])
            if set(witness["scales"]) != set(exact):
                raise ValueError("native response witness omitted a function")
            for name, value in exact.items():
                actual = _finite(witness["scales"][name], "native response")
                reference = float(value)
                tolerance = 1e-10 + 1e-8 * abs(reference)
                if abs(actual - reference) > tolerance:
                    raise ValueError("native RooFit response differs from exact source polynomial")
                comparisons.append({"point": witness["point"], "function": name, "actual": actual,
                                    **({"reference_mean": reference, "reference_kind": "supplied regional mean algebra"} if construction else {"exact_rational": eft._ratio(value)}), "tolerance": tolerance})
    return comparisons


def _derivative_context(config, native_configuration, raw, workspace, work, *, expected_preparation=None):
    from ravel.physics.combine_derivatives import digest
    graph_state = {}
    if 'source_graph' in config['model']:
        d = read_json(work/'ravel_source_response.json')['document']
        graph_state = {p['name']:{'value':float(eft.rational(p['initial'])),'minimum':float(eft.rational(p['bounds'][0])),
                                 'maximum':float(eft.rational(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
        graph_state.update({'ravel_aux_'+str(i):{'value':0.,'minimum':float(eft.rational(b[0])),'maximum':float(eft.rational(b[1])),'constant':False}
                            for i,b in enumerate(d['auxiliary']['eta_bounds'])})
        if expected_preparation is not None:graph_state=expected_preparation['generating_state']
    return {"model_sha256": digest({"source": config["source"], "model": config["model"], "effective_card_sha256": hashlib.sha256(raw).hexdigest()}),
            "runtime_binding_sha256": digest(native_configuration["runtime"]),
            "definition": {"workspace_sha256": _hash(workspace), "native_configuration_sha256": _hash(work / "ravel_native_configuration.json"),
                "native_root_version": native_configuration["runtime"]["expected"]["root_version"],
                "selection": config["derivatives"], "declared_poi_domain": {"name": config["fit"]["poi"], "bounds": [float(eft.rational(v)) for v in config["fit"]["domain"]]},
                "worker_sha256": hashlib.sha256(NATIVE_PROBE.encode()).hexdigest(),
                "staged_implementation": {name: _hash(work / name) for name in (("ravel_combine_derivatives.py", "ravel_derivative_kernel.py") + (("ravel_regional_fixed_state.py",) if "fixed_state_observer" in config else ()))},
                "evaluation": "Existing ModelConfig PDF createNLL(data_obs, RooLinkedList Constrain/GlobalObservables); unchanged ROOT/custom-PDF defaults; no fit/no factor2",
                **({"data_semantics":"generated_source_graph_Asimov_not_observed" if expected_preparation is not None else "original_observed_source_graph_counts",
                    "expected_preparation_sha256":digest(expected_preparation) if expected_preparation is not None else None,
                    "source_graph_cell":config["model"]["source_graph"]["cell"],"source_graph_initial_state":graph_state,
                    "source_response_sha256":_hash(work/'ravel_source_response.json')} if "source_graph" in config["model"] else {})}}


def _extract_derivatives(probe, config, context, kernel):
    from ravel.physics.combine_derivatives import validate_delivery
    delivery = probe.get("derivatives")
    estimates = validate_delivery(delivery, config["derivatives"], context, context["definition"]["declared_poi_domain"], kernel)
    mc = delivery["definition"]["initial_state"]["model_config"]
    for key in ("pois", "nuisances", "observables", "global_observables"):
        if mc[key] != probe["workspace"][key]:
            raise ValueError("derivative actual ModelConfig population differs from workspace probe")
    if delivery["definition"]["observed_data"]["entries"] != probe["workspace"]["data_entries"]:
        raise ValueError("derivative observed data denominator differs from workspace probe")
    graph_fields = {}
    if "source_graph" in config["model"]:
        definition = delivery['definition']
        census = definition['observed_data']
        expected_counts = probe['construction_observations']['counts']
        actual = {q['name']:q['value'] for q in census['rows'][0]['coordinates'] if q['kind']=='real'}
        if census['entries'] != 1 or census['rows'][0]['weight'] != 1. or actual != {'n_obs_bin'+n:v for n,v in expected_counts.items()}:
            raise ValueError('source graph derivative complete dataset differs from bound workspace observations')
        declared = context['definition']
        parameters = {p['name']:p for p in definition['initial_state']['parameters']}
        for name,row in declared['source_graph_initial_state'].items():
            p=parameters.get(name)
            if p is None or {'value':p['value'],'minimum':p['bounds']['min'],'maximum':p['bounds']['max'],'constant':p['constant']} != row:
                raise ValueError('source graph diagnostic initial complete source/generated coordinate state changed')
        graph_fields = {'source_graph_cell':declared['source_graph_cell'],'data_semantics':declared['data_semantics'],
                        'expected_preparation_sha256':declared['expected_preparation_sha256'],
                        'numerical_equivalence_qualified':False,'coverage_qualified':False}
    return {"kind": "selected_axis_native_NLL_derivative_diagnostics", "passed": True, "fit_calls": 0, **graph_fields,
            "native_nll_calls": delivery["native_nll_calls"], "estimates": estimates,
            "profiler_derivative_qualified": False, "globality_qualified": False, "inference_qualified": False,
            "scope": "Finite fixed-point delivery only; actual native/analytic acceptance remains an ordinary review obligation"}


def _run(task, base, out):
    from ravel.workflow.science import regular
    # One existing observation binds classification and the input census before
    # native launch; no validation cache survives that authority boundary.
    from ravel.workflow.science import _validation_scope
    with _validation_scope(base) as session:
        config, cp, files, tools, artifacts, physics_path, census, raw, response, binding, dependencies, replacement = _configuration(task, base, _session=session)
        pinned = inputs(task, base, _session=session)
        before = {str(p): session.hash_file(p) for p in pinned}
        shape_buffers = {}
        shape_binding = None
        if "calibration" in config and "source_graph" not in config["model"]:
            from ravel.physics import regional_calibration
            shape_sources = regional_calibration.shape_source_paths(response['document'])
            if shape_sources:
                import stat
                from ravel.workflow.validation_io import identity as file_identity
                shape_binding = {"kind": regional_calibration.SHAPE_SOURCE_KIND, "files": {}}
                for name, src in zip(regional_calibration.SHAPE_SOURCE_MEMBERS, shape_sources):
                    observed = session.observe(src)
                    if not 0 < observed[3] <= 1048576:
                        raise ValueError("bounded calibration shape source required")
                    # The consumed buffer is checked against the original input
                    # commitment. Neither the staged copy nor its binding is
                    # recaptured from a later pathname read.
                    descriptor = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    try:
                        opened = os.fstat(descriptor)
                        if not stat.S_ISREG(opened.st_mode) or file_identity(opened) != observed:
                            raise ValueError("calibration shape source changed before capture")
                        chunks = []
                        consumed = 0
                        while consumed <= observed[3]:
                            chunk = os.read(descriptor, observed[3] + 1 - consumed)
                            if not chunk:
                                break
                            chunks.append(chunk); consumed += len(chunk)
                        source_bytes = b''.join(chunks)
                        if file_identity(os.fstat(descriptor)) != observed:
                            raise ValueError("calibration shape source changed during capture")
                    finally:
                        os.close(descriptor)
                    if (session.observe(src) != observed or len(source_bytes) != observed[3]
                            or hashlib.sha256(source_bytes).hexdigest() != before[str(src)]):
                        raise ValueError("calibration shape source differs from approved input")
                    shape_buffers[name] = source_bytes
                    shape_binding['files'][name] = {"sha256": before[str(src)], "bytes": len(source_bytes)}
    out = Path(out).absolute()
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("native attempt directory must not traverse a symlink")
    out.mkdir(parents=True, exist_ok=True)
    work = out / "native-work"
    work.mkdir(exist_ok=False)
    logs = out / "native-logs"
    logs.mkdir(exist_ok=False)
    for name, path in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    card = work / config["model"]["card"]
    card.write_bytes(raw)
    native_config = work / "ravel_native_configuration.json"
    native_configuration = json.loads(json.dumps(config))
    for pin, path in zip(native_configuration["runtime"]["artifacts"], artifacts):
        pin["path"] = str(path)
    for name, path in tools.items():
        native_configuration["runtime"]["tools"][name]["path"] = str(path)
    if "expected_data" in config or 'source_graph'in config['model']:
        from ravel.physics import regional_expected
        src=Path(regional_expected.__file__)
        if _hash(src)!=before[str(src)]:raise ValueError("expected implementation differs from approved input")
        shutil.copyfile(src,work/"ravel_regional_expected.py")
        native_configuration["expected_implementation_sha256"]=_hash(src)
        if 'source_graph'in config['model']:native_configuration['graph_observer_implementation_sha256']=_hash(src)
    if "calibration" in config:
        from ravel.physics import regional_expected, regional_calibration
        for module, name, key in ((regional_expected,"ravel_regional_expected.py","calibration_optimizer_sha256"), (regional_calibration,"ravel_regional_calibration.py","calibration_implementation_sha256")):
            src=Path(module.__file__)
            if _hash(src)!=before[str(src)]:raise ValueError("calibration implementation differs from approved input")
            shutil.copyfile(src,work/name); native_configuration[key]=_hash(src)
        if 'source_graph' in config['model']:
            from ravel.physics import source_graph_calibration,combine_derivatives
            for module,name,key in ((source_graph_calibration,'ravel_source_graph_calibration.py','graph_calibration_implementation_sha256'),(combine_derivatives,'ravel_graph_state.py','graph_state_implementation_sha256')):
                src=Path(module.__file__)
                if _hash(src)!=before[str(src)]:raise ValueError('graph calibration implementation differs from admitted source')
                shutil.copyfile(src,work/name);native_configuration[key]=_hash(src)
        if shape_binding is not None:
            for name, source_bytes in shape_buffers.items():
                target=work/"ravel_calibration_source"/"ravel"/name
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source_bytes)
            regional_calibration.check_shape_sources(work,shape_binding,imported=False)
            native_configuration['calibration_shape_sources']=shape_binding
    if "discovery_diagnostic" in config:
        from ravel.physics import discovery_heldout, combine_derivatives
        for module,name,key in ((discovery_heldout,'ravel_discovery_heldout.py','discovery_implementation_sha256'),
                               (combine_derivatives,'ravel_graph_state.py','discovery_state_implementation_sha256')):
            src=Path(module.__file__)
            if _hash(src)!=before[str(src)]:raise ValueError('discovery implementation differs from approved input')
            shutil.copyfile(src,work/name);native_configuration[key]=_hash(src)
    atomic_json(native_config, native_configuration)
    probe_script = work / "ravel_native_probe.py"
    probe_script.write_text(NATIVE_PROBE)
    if config["schema_version"] == 3:
        from ravel.physics import combine_derivatives, native_likelihood_derivatives
        staged_modules = [(combine_derivatives, "ravel_combine_derivatives.py"), (native_likelihood_derivatives, "ravel_derivative_kernel.py")]
        if "fixed_state_observer" in config:
            from ravel.physics import regional_fixed_state
            staged_modules.append((regional_fixed_state, "ravel_regional_fixed_state.py"))
        for module, name in staged_modules:
            source = Path(module.__file__)
            if _hash(source) != before[str(source)]:
                raise ValueError("derivative implementation differs from approved input")
            shutil.copyfile(source, work / name)
    result_script = work / "ravel_native_result.py"
    result_script.write_text(NATIVE_RESULT)
    response_path = work / "ravel_source_response.json"
    if response:
        if response.get("kind") == "native-source-graph/v1":
            from ravel.physics import native_statistical_construction as graph
            bridge = graph.native_bridge_source(response)
        elif response.get("kind") == "regional-poisson-construction/v1":
            from ravel.physics import statistical_construction as regional
            bridge = regional.native_bridge_source(response)
        else:
            bridge = eft.native_bridge_source(response)
        (work / "ravel_source_response.py").write_text(bridge)
        atomic_json(response_path, response)
    # Resolve shape paths relative to the card directory. Include bridge on path.
    cwd = card.parent
    env = {"HOME": str(work), "TMPDIR": str(work), "LC_ALL": "C", "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    env.update(config["runtime"]["environment"])
    env["PYTHONPATH"] = str(work) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    deadline = time.monotonic() + config["max_seconds"]
    transport = json.loads(json.dumps(config["runtime"]["transport"]))
    if transport["kind"] == "podman":
        transport["executable"]["path"] = str(_pin(transport["executable"], cp.parent, executable=True))
        inspect_command = [transport["executable"]["path"], "--connection", transport["connection"], "image", "inspect", transport["image_id"]]
        inspect_log = _process(inspect_command, work, {"LC_ALL": "C", **transport["client_environment"]}, logs / "image-inspect.log", deadline)
        image = json.loads(inspect_log)
        if len(image) != 1 or ("sha256:" + image[0]["Id"].removeprefix("sha256:")) != transport["image_id"] or image[0].get("Architecture") != "amd64" or image[0].get("Os") != "linux":
            raise ValueError("observed native image differs from the approved source identity/architecture")
        atomic_json(out / "native-image-identity.json", image)
    def invoke(command, log_name, *, expected_returncode=0):
        return _process(command, cwd, env, logs / log_name, deadline, transport=transport, out=out,
                        expected_returncode=expected_returncode)
    build, fit_command = commands(config, tools, work, has_response=response is not None)
    identity_command = [str(tools["python"]), str(probe_script), str(native_config)]
    command_manifest = {"combine_help": [str(tools["combine"]), "--help"], "combine_version": [str(tools["combine"])],
                        "version_proof": config["runtime"]["version_proof"],
                        "native_identity": identity_command, "workspace_build": build, "fit": fit_command}
    atomic_json(out / "native-command-plan.json", command_manifest)
    invoke(command_manifest["combine_help"], "combine-help.log")
    version_log = invoke(command_manifest["combine_version"], "combine-version.log",
                         expected_returncode=config["runtime"]["version_proof"]["expected_returncode"])
    version = config["runtime"]["expected"]["combine_version"]
    version_identity = _combine_version_identity(version_log, version)
    identity = _probe_result(invoke(identity_command, "native-identity.log"))
    _check_probe(identity, config["runtime"]["expected"], artifacts, native_configuration["runtime"])
    identity["version_proof"] = version_identity
    invoke(build, "workspace-build.log")
    workspace = regular(work / "ravel_workspace.root", work)
    derivative_context = None
    if config["schema_version"] == 3 and "source_graph" not in config["model"]:
        from ravel.physics import combine_derivatives, native_likelihood_derivatives
        derivative_context = _derivative_context(config, native_configuration, raw, workspace, work)
        atomic_json(work / "ravel_derivative_context.json", derivative_context)
    workspace_command = identity_command + [str(workspace)] + ([str(response_path)] if response else [])
    command_manifest["workspace_probe"] = workspace_command
    atomic_json(out / "native-command-plan.json", command_manifest)
    probe = _probe_result(invoke(workspace_command, "workspace-probe.log"))
    _check_probe(probe, config["runtime"]["expected"], artifacts, native_configuration["runtime"])
    comparisons = _check_workspace(probe, config, response)
    if "expected_data" in config:
        probe["data_semantics"]=("build_scaffold_not_observed" if config["expected_data"]["conditioning"]=="supplied_nominal" else "actual_integer_observed_conditioning_input")
    expected_preparation=None; expected_protected={}
    if "expected_data" in config:
        from ravel.physics import regional_expected
        expected_protected={str(p):_hash(p) for p in (workspace,native_config,probe_script,response_path,work/"ravel_regional_expected.py",work/"ravel_source_response.py")}
        prepare_command=workspace_command+["--prepare-expected"]
        command_manifest["expected_preparation"]=prepare_command
        atomic_json(out/"native-command-plan.json",command_manifest)
        prepared_probe=_probe_result(invoke(prepare_command,"expected-preparation.log"))
        _check_probe(prepared_probe,config["runtime"]["expected"],artifacts,native_configuration["runtime"])
        expected_preparation=prepared_probe["expected_preparation"]
        if read_json(work/"ravel_expected_preparation.json")!=expected_preparation:raise ValueError("durable expected preparation differs")
        if response.get('kind')=='native-source-graph/v1':
            graph.validate_expected_delivery(expected_preparation,response)
            if expected_preparation.get('count_domains')!=probe.get('construction_count_domains'):raise ValueError('expected generation changed original count observable domains')
        else:regional_expected.validate_delivery(expected_preparation,response)
        if expected_preparation['conditioning_fit']['performed']:
            raw_fit=regular(work/'ravel_expected_preparation.fit.root',work)
            if expected_preparation['conditioning_fit']['raw_result']!={'basename':raw_fit.name,'sha256':_hash(raw_fit),'bytes':raw_fit.stat().st_size}:
                raise ValueError('literal conditioning fit file differs from native return')
            expected_protected[str(raw_fit)]=_hash(raw_fit)
        expected_workspace=regular(work/"ravel_expected_workspace.root",work)
        prepared_command=identity_command+[str(expected_workspace),str(response_path)]
        command_manifest["expected_workspace_probe"]=prepared_command
        atomic_json(out/"native-command-plan.json",command_manifest)
        expected_probe=_probe_result(invoke(prepared_command,"expected-workspace-probe.log"))
        _check_probe(expected_probe,config["runtime"]["expected"],artifacts,native_configuration["runtime"])
        comparisons+=_check_workspace(expected_probe,config,response,expected_preparation)
        expected_preparation["workspace_probe"]=expected_probe
        atomic_json(out/"native-expected-data.json",expected_preparation)
        expected_protected.update({str(p):_hash(p) for p in (expected_workspace,work/"ravel_expected_preparation.json",out/"native-expected-data.json")})
    calibration_protected={}
    if "discovery_diagnostic" in config:
        from ravel.physics import discovery_heldout,regional_expected
        discovery_protected={str(work/name):_hash(work/name) for name in ('ravel_discovery_heldout.py','ravel_graph_state.py')}
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('aggregate native discovery budget exhausted')
        discovery_command=prepared_command+['--discovery',repr(remaining)]
        command_manifest['fit']=None;command_manifest['discovery']=discovery_command
        command_manifest['discovery_resource_contract']={
            'planned_starts':config['discovery_diagnostic']['starts'],
            'maximum_top_level_profiles':config['discovery_diagnostic']['max_fit_calls'],
            'maximum_common_nll_readbacks':config['discovery_diagnostic']['max_readbacks'],
            'profile_policy':regional_expected.PROFILE_POLICY,'native_wall_seconds':config['max_seconds'],
            'scope':'One original total/native wall ceiling, no retries. Hesse/internal objective calls retain existing per-fit limits.'}
        atomic_json(out/'native-command-plan.json',command_manifest)
        discovery_log=invoke(discovery_command,'native-discovery.log')
        discovery_probe=_probe_result(discovery_log)
        _check_probe(discovery_probe,config['runtime']['expected'],artifacts,native_configuration['runtime'])
        delivery=discovery_probe['discovery']
        if read_json(work/'ravel_discovery_heldout_journal.json')!=delivery:raise ValueError('durable discovery journal differs')
        # The journal embeds the strict native preparation, not the host's
        # augmented workspace-probe wrapper. Both must name the same data law.
        original_preparation=read_json(work/'ravel_expected_preparation.json')
        if delivery['generation']!=original_preparation:raise ValueError('discovery regenerated or relabelled original Asimov data')
        graph.validate_expected_delivery(original_preparation,response)
        discovery_heldout.validate_delivery(delivery,response,config['discovery_diagnostic'],regional_expected)
        raw_names=set()
        for row in delivery['profiles']:
            graph.integration_witness(row['integrals'],response)
            if row['fit']['performed']:
                pin=row['fit']['raw_result'];path=regular(work/pin['basename'],work)
                if pin!={'basename':path.name,'sha256':_hash(path),'bytes':path.stat().st_size}:raise ValueError('raw discovery fit file differs')
                raw_names.add(path.name);discovery_protected[str(path)]=pin['sha256']
        if {p.name for p in work.glob('ravel_discovery_heldout_*.root')}!=raw_names:raise ValueError('unissued/extra discovery fit files differ')
        if any(_hash(Path(p))!=h for p,h in {**expected_protected,**discovery_protected}.items()):raise ValueError('discovery changed source/workspace/helper custody')
        expected_protected.update(discovery_protected)
        expected_protected[str(work/'ravel_discovery_heldout_journal.json')]=_hash(work/'ravel_discovery_heldout_journal.json')
        extracted={'kind':discovery_heldout.KIND,'passed':True,'delivery':delivery,
            'scope':'Paired fixed-source nonzero-signal Asimov discovery diagnostic; local expected asymptotic proxy only. No observed/global significance, global optimum, coverage or physical acceptance.'}
        atomic_json(out/'native-discovery.json',extracted)
        warning_lines=[{'line':i,'text':line} for i,line in enumerate(discovery_log.splitlines(),1) if re.search(r'warning|error|fail|invalid|converg|covariance|hesse|status',line,re.I)]
    elif "calibration" in config:
        from ravel.physics import regional_expected, regional_calibration
        calibration_protected={str(p):_hash(p) for p in (workspace,native_config,probe_script,response_path,work/"ravel_regional_expected.py",work/"ravel_regional_calibration.py",work/"ravel_source_response.py")}
        if 'source_graph' in config['model']:
            from ravel.physics import source_graph_calibration
            calibration_protected.update({str(work/name):_hash(work/name)for name in ('ravel_source_graph_calibration.py','ravel_graph_state.py')})
        if "calibration_shape_sources" in native_configuration:
            calibration_protected.update({str(work/"ravel_calibration_source"/"ravel"/name):pin['sha256'] for name,pin in native_configuration['calibration_shape_sources']['files'].items()})
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError("aggregate native calibration budget exhausted")
        calibration_command=workspace_command+["--calibrate",repr(remaining)]
        command_manifest["fit"]=None;command_manifest["calibration"]=calibration_command
        command_manifest["calibration_resource_contract"]={"scheduled_toys":len(config['calibration']['truths'])*config['calibration']['trials_per_truth'],"maximum_top_level_profiles":2*len(config['calibration']['truths'])*config['calibration']['trials_per_truth'],"profile_policy":regional_expected.PROFILE_POLICY,"scope":"Hesse/internal minimizer work is additional; one original outer/native wall ceiling, no retries"}
        if 'source_graph' in config['model']:
            command_manifest['calibration_resource_contract'].update(source_graph_calibration.prospective(config['calibration'],response))
        atomic_json(out/"native-command-plan.json",command_manifest)
        calibration_log=invoke(calibration_command,"native-calibration.log")
        calibration_probe=_probe_result(calibration_log)
        _check_probe(calibration_probe,config["runtime"]["expected"],artifacts,native_configuration["runtime"])
        delivery=calibration_probe['calibration']
        if read_json(work/"ravel_calibration_journal.json")!=delivery:raise ValueError("durable calibration journal differs")
        validation_reference = regional_calibration.ReferenceAudit(config['calibration'],response['document'],'validation') if 'source_graph' not in config['model'] and regional_calibration.has_dijet(response['document']) else None
        if validation_reference is not None:
            validation_path=out/'native-calibration-reference-validation.json'
            validation_reference.checkpoint=lambda:regional_calibration._write(validation_path,validation_reference.evidence)
            validation_reference.save()
        if 'source_graph' in config['model']:
            source_graph_calibration.validate_delivery(delivery,response,config['calibration'],regional_expected,regional_calibration)
            for snapshot in delivery['native_readback_cost']['snapshots']:
                if snapshot['status']=='returned':
                    from ravel.physics import native_statistical_construction as graph
                    graph.integration_witness(snapshot['integrals'],response)
            from ravel.physics.ma5_saf import Capture
            state_capture=Capture();state_buffers={}
            for row in delivery['rows']:
                for draw in row.get('native_sampler',{}).get('draws',[]):
                    for phase in ('before','after'):
                        pin=draw.get(phase,{})
                        if pin.get('status')=='written':
                            path,raw_state=state_capture.read(pin['basename'],work)
                            if pin['sha256']!=hashlib.sha256(raw_state).hexdigest() or pin['bytes']!=len(raw_state):raise ValueError('whole native RNG state changed')
                            state_buffers[pin['basename']]=raw_state
                            calibration_protected[str(path)]=pin['sha256']
            state_capture.finish();source_graph_calibration.validate_rng_states(delivery,state_buffers)
        else:regional_calibration.validate_delivery(delivery,response,config['calibration'],regional_expected,reference=validation_reference)
        if validation_reference is not None:
            validation_reference.save()
            calibration_protected[str(validation_path)]=_hash(validation_path)
        for row in delivery['rows']:
            for role in ('free','fixed'):
                fit=row.get(role,{}).get('fit',{})
                if fit.get('performed'):
                    pin=fit['raw_result']; path=regular(work/pin['basename'],work)
                    if pin!={'basename':path.name,'sha256':_hash(path),'bytes':path.stat().st_size}:raise ValueError("calibration raw fit result changed")
                    calibration_protected[str(path)]=pin['sha256']
        if any(_hash(Path(p))!=h for p,h in calibration_protected.items()):raise ValueError("calibration source/workspace changed")
        extracted={"kind":delivery['kind'],"passed":True,"delivery":delivery,"scope":"Complete fixed-truth pointwise calibration diagnostics with every unresolved/unissued trial; no globality or physics acceptance"}
        if validation_reference is not None: extracted["validation_reference_audit"]=validation_reference.evidence
        atomic_json(out/"native-calibration.json",extracted)
        warning_lines=[{"line":i,"text":line} for i,line in enumerate(calibration_log.splitlines(),1) if re.search(r"warning|error|fail|invalid|converg|covariance|hesse|status",line,re.I)]
    elif config["schema_version"] == 3:
        if "source_graph" in config["model"]:
            diagnostic_workspace = expected_workspace if expected_preparation is not None else workspace
            derivative_context = _derivative_context(config,native_configuration,raw,diagnostic_workspace,work,expected_preparation=expected_preparation)
            atomic_json(work / "ravel_derivative_context.json",derivative_context)
            diagnostic_command = identity_command+[str(diagnostic_workspace),str(response_path),"--diagnose-source-graph"]
            command_manifest['source_graph_diagnostics'] = diagnostic_command
            command_manifest['source_graph_diagnostic_resource_contract'] = {
                'maximum_native_nll_calls':config['derivatives']['max_points'],'diagnostic_fit_calls':0,
                'expected_conditioning_fit_calls':int(bool(expected_preparation and expected_preparation['conditioning_fit']['performed'])),
                'integral_internal_evaluations':'unknown; original native integral settings and aggregate wall apply',
                'native_wall_seconds':config['max_seconds'],'retries':0,'dataset':derivative_context['definition']['data_semantics']}
            atomic_json(out / "native-command-plan.json",command_manifest)
            diagnostic_log = invoke(diagnostic_command,"source-graph-diagnostics.log")
            probe = _probe_result(diagnostic_log)
            _check_probe(probe,config['runtime']['expected'],artifacts,native_configuration['runtime'])
            comparisons += _check_workspace(probe,config,response,expected_preparation)
        if 'source_graph' in config['model'] and _hash(response_path)!=derivative_context['definition']['source_response_sha256']:raise ValueError('source graph diagnostic response changed')
        retained_journal = combine_derivatives.read_journal(regular(work / "ravel_derivative_points.jsonl", work))
        if not combine_derivatives._same(retained_journal, probe["derivatives"]["point_journal"]):
            raise ValueError("durable native point journal differs from successful payload")
        extracted = _extract_derivatives(probe, config, derivative_context, native_likelihood_derivatives)
        if "fixed_state_observer" in config:
            from ravel.physics import regional_fixed_state
            observer_delivery = probe["fixed_state_observer"]
            if not combine_derivatives._same(observer_delivery["initial_state"], probe["derivatives"]["final_state"]) or not combine_derivatives._same(observer_delivery["observed_data"], probe["derivatives"]["definition"]["observed_data"]):
                raise ValueError("fixed observer changed the preceding ModelConfig/data definition")
            observer_journal = combine_derivatives.read_journal(regular(work / "ravel_fixed_state_points.jsonl", work))
            if not combine_derivatives._same(observer_journal, observer_delivery["journal"]):
                raise ValueError("fixed-state durable raw journal differs")
            extracted["fixed_state_observer"] = regional_fixed_state.validate_delivery(observer_delivery, config["fixed_state_observer"], response, combine_derivatives)
            extracted["native_nll_calls"] += observer_delivery["calls"]["nll"]
            atomic_json(out / "native-fixed-state-observations.json", observer_delivery)
        atomic_json(out / "native-derivative-plan.json", probe["derivatives"]["plan"])
        atomic_json(out / "native-derivative-observations.json", probe["derivatives"]["observations"])
        atomic_json(out / "native-derivative-estimates.json", probe["derivatives"]["estimates"])
        warning_lines = ([{"line":i,"text":line} for i,line in enumerate(diagnostic_log.splitlines(),1)
                          if re.search(r"warning|error|fail|invalid|converg|covariance|hesse|status",line,re.I)] if "source_graph" in config["model"] else [])
        if "source_graph" in config["model"]:
            extracted['expected_conditioning_fit_calls'] = int(bool(expected_preparation and expected_preparation['conditioning_fit']['performed']))
        if read_json(work / "ravel_derivative_context.json") != derivative_context:
            raise ValueError("derivative context changed during native execution")
        for name, sha in derivative_context["definition"]["staged_implementation"].items():
            if _hash(work / name) != sha:
                raise ValueError("staged derivative implementation changed")
        if _hash(diagnostic_workspace if "source_graph" in config["model"] else workspace) != derivative_context["definition"]["workspace_sha256"] or _hash(probe_script) != derivative_context["definition"]["worker_sha256"]:
            raise ValueError("derivative native workspace/worker changed")
    else:
        fit_log = invoke(fit_command, "native-fit.log")
        warning_lines = [{"line": i, "text": line} for i, line in enumerate(fit_log.splitlines(), 1)
                         if re.search(r"warning|error|fail|invalid|converg|covariance|hesse|status", line, re.I)]
        root_files = list(cwd.glob("higgsCombine.ravel." + config["fit"]["method"] + ".mH*.root"))
        if len(root_files) != 1:
            raise ValueError("native fit must produce exactly one declared limit ROOT file")
        output_root = regular(root_files[0], work)
        result_command = [str(tools["python"]), str(result_script), str(output_root), str(native_config)]
        if config["fit"]["method"] == "MultiDimFit":
            diagnostic_files = sorted(cwd.glob("multidimfit.ravel*.root"))
            result_command += [str(regular(p, work)) for p in diagnostic_files]
        command_manifest["result_extraction"] = result_command
        atomic_json(out / "native-command-plan.json", command_manifest)
        extraction_fit=({**config['fit'],'data':'observed'} if 'source_graph'in config['model'] and 'expected_data'in config else config['fit'])
        # The saved best-fit/tree format is the same; generated data identity remains explicit.
        extracted = extract_native_result(invoke(result_command, "native-result.log"), extraction_fit)
        if 'source_graph'in config['model'] and 'expected_data'in config:
            extracted.update(data_semantics='generated_source_graph_Asimov_not_observed',observed_endpoint=None)
        if config["schema_version"] == 2:
            _check_saved_population(extracted, probe)
        if "expected_data" in config and 'source_graph'not in config['model']:
            if any(_hash(Path(p))!=h for p,h in expected_protected.items()):
                raise ValueError("native expected source/workspace/dataset evidence changed")
            atomic_json(out/"native-expected-combine-result.json",extracted)
            request_path=work/"ravel_expected_crossing_request.json"
            request={"inference":extracted,"fit":config["fit"],"preparation":expected_preparation}
            atomic_json(request_path,request)
            expected_protected.update({str(p):_hash(p) for p in (request_path,output_root,out/"native-expected-combine-result.json")})
            crossing_command=prepared_command+["--qualify-expected",_hash(request_path)]
            command_manifest["expected_crossing_qualification"]=crossing_command
            atomic_json(out/"native-command-plan.json",command_manifest)
            crossing_probe=_probe_result(invoke(crossing_command,"expected-crossings.log"))
            _check_probe(crossing_probe,config["runtime"]["expected"],artifacts,native_configuration["runtime"])
            crossing=crossing_probe["expected_crossings"]
            if read_json(work/"ravel_expected_crossings.json")!=crossing:raise ValueError("durable crossing evidence differs")
            raw_profiles=set()
            for row in crossing["profiles"]:
                if row["fit"]["performed"]:
                    pin=row["fit"]["raw_result"]
                    if Path(pin["basename"]).name!=pin["basename"]:raise ValueError("invalid profile result basename")
                    path=regular(work/pin["basename"],work)
                    if pin!={"basename":path.name,"sha256":_hash(path),"bytes":path.stat().st_size} or path.name in raw_profiles:raise ValueError("raw profile result differs or is duplicated")
                    raw_profiles.add(path.name);expected_protected[str(path)]=_hash(path)
            if {p.name for p in work.glob("ravel_expected_profile_*")}!=raw_profiles:raise ValueError("profile raw output census differs")
            atomic_json(out/"native-expected-crossings.json",crossing)
            expected_protected.update({str(p):_hash(p) for p in (work/"ravel_expected_crossings.json",out/"native-expected-crossings.json")})
            regional_expected.check_limits(extracted,config["fit"],crossing,response,expected_preparation)
    if any(_hash(Path(p))!=h for p,h in {**expected_protected,**calibration_protected}.items()):
        raise ValueError("native source/workspace/dataset evidence changed")
    if {str(p): _hash(p) for p in pinned} != before:
        raise ValueError("native source/runtime inputs changed during execution")
    # Original model files must survive staging and fitting unchanged, except the
    # admitted replacement card whose exact result bytes are independently bound.
    for name, source in files.items():
        expected_hash = hashlib.sha256(raw).hexdigest() if name == config["model"]["card"] else _hash(source)
        if _hash(work / name) != expected_hash:
            raise ValueError("native process changed a staged original model asset")
    retained = [{"path": p.relative_to(out).as_posix(), "sha256": _hash(p), "bytes": p.stat().st_size}
                for p in sorted(out.rglob("*")) if p.is_file()]
    result = {"status": "passed" if extracted["passed"] else "failed", "physics_validated": False,
              "scope": ("Same-dataset source-Asimov paired profiles; local expected discovery diagnostic only, no observed/global/coverage or physics certificate" if "discovery_diagnostic" in config else "Selected-axis complete source-graph native fixed-NLL diagnostics; observed/generated data identity retained, no independent numerical reference, globality or inference certificate" if config["schema_version"]==3 and "source_graph" in config["model"] else "Complete source-graph generated Asimov/profile delivery; native structure/data readback only, no numerical convergence/coverage/globality certificate" if expected_preparation is not None and 'source_graph'in config['model'] else "Complete pointwise full-auxiliary calibration delivery; failures retained, no coverage adequacy/globality qualification" if "calibration" in config else "Expected-only Asimov CLs projection from the explicit source/background-conditioning law; no observed endpoint or coverage certification" if expected_preparation is not None else "Native full supplied CMS likelihood with bound model, source-compatible observed runtime and retained rows"),
              "source": config["source"], "runtime_identity": identity, "workspace_probe": probe,
              **({"expected_data":expected_preparation} if expected_preparation is not None else {}),
              "native_function_comparisons": comparisons, "card_census": census,
              "regions": config["model"]["regions"], "shape_dependencies": dependencies,
              "response_binding": binding, "signal_replacement": replacement, "fit": None if config["schema_version"] == 3 or "calibration" in config or "discovery_diagnostic" in config else config["fit"],
              "inference": extracted, "original_input_hashes": before, "commands": command_manifest,
              **({'integration_diagnostics':{'numerical_equivalence_qualified':False,'convergence':'unknown','requested_settings':response['recipe']['cells'][next(i for i,c in enumerate(response['recipe']['cells'])if c['id']==response['cell'])]['integration'],'observed_integrals':probe.get('source_graph_integrals'),'raw_log_artifacts':[r for r in retained if r['path'].startswith('native-logs/')],'scope':'Full native logs and exact returned metadata; absent warnings or optimizer success cannot certify joint integrals'}} if response and response.get('kind')=='native-source-graph/v1' else {}),
              "optimizer_log_audit": {"matching_lines": warning_lines, "requires_review": bool(warning_lines),
                                      "scope": "Literal diagnostic lines, including successful and recovered optimizer steps; reviewers must adjudicate them. Command exit and quantile agreement alone do not prove fit convergence."},
              "retained_artifacts": retained, "runtime_qualified_for_this_workspace": True,
              "limitations": ["Runtime qualification applies to the executed source/workspace, not every CMS model.",
                              "Unchanged source nuisance/auxiliary semantics are retained in native Combine.",
                              "Raw fixed NLL witnesses use source nuisance values; they are not conditional profile fits.",
                              "Derivative v3 observes a selected-axis finite stencil of the existing NLL with full resets; h/h2 agreement does not qualify smoothness, error bounds or profiler use.",
                              "ROOT files and native optimizer logs are retained. Finite tree rows do not certify optimizer globality, coverage, detector response or EFT validity.",
                              "Asymptotic example agreement is separate from a paper's toy-based inference."]}
    if shape_binding is not None:
        # The native worker checked copied import origins. At host delivery,
        # revalidate the entire closed package, not only its known leaves.
        regional_calibration.check_shape_sources(work,shape_binding,imported=False)
    atomic_json(out / "native-likelihood.json", result)
    return result


def run(task, base, out):
    """Return honest failed delivery while preserving every native failure log."""
    try:
        return _run(task, base, out)
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as exc:
        out = Path(out).absolute()
        if any(p.is_symlink() for p in (out, *out.parents)):
            raise
        out.mkdir(parents=True, exist_ok=True)
        retained = [{"path": p.relative_to(out).as_posix(), "sha256": _hash(p), "bytes": p.stat().st_size}
                    for p in sorted(out.rglob("*")) if p.is_file() and not p.is_symlink()]
        result = {"status": "failed", "physics_validated": False,
                  "scope": "Retained unsuccessful native CMS attempt; no numerical/reference or physics acceptance",
                  "error": {"type": type(exc).__name__, "message": str(exc)},
                  "retained_artifacts": retained,
                  "runtime_qualified_for_this_workspace": False,
                  "custody_status": "Successful end-of-attempt custody checks were not reached; inspect retained stage/input snapshots and logs.",
                  "limitations": ["A failed build, probe, fit or extraction is preserved as a failure, not a likelihood result.",
                                  "No automated new attempt or changed numerical setting is authorized."]}
        atomic_json(out / "native-likelihood.json", result)
        return result
