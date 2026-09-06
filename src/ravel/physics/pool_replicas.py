"""Pool independently seeded, uniform-positive-weight native LO replicas.

The manifest is explicit and source-bound::

  {"schema_version": 1, "input_combination": "pool-independent-replicas",
   "replicas": [{"plan": {"path": "run/inputs/native_execution_plan.json",
                           "sha256": "..."}}]}

At least two completed native explicit-card replicas of the same physics are
required. The per-replica normalized rate estimator is weighted by its original
generated exposure N_j / sum(N), never by selected rows. This is an exposure-
weighted mean of independent rate estimates, not an additive process sum or an
inverse-variance average. The finite-MC moments condition on each recorded
generator cross-section estimate; its integration uncertainty remains separate.
MG, shower and detector seeds must all be distinct across replicas. Common
random-number detector controls require a covariance model and are not supported
by this independent-event pooling adapter.

python -m ravel.physics.pool_replicas --manifest replicas.json --out new-pool
Creates pooled.root and pooling.json in a NEW directory. No generation or fits.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
from pathlib import Path
import re

from ravel.physics.native_normalization import fingerprint, load_normalization, weight_summary
from ravel.physics.native_pipeline import card_assignments, plan_hash, read_config, validate_process_card, validate_param_card
from ravel.workflow.execution import digest, load_execution, snapshot
from ravel.workflow.state_io import read_json


def pinned(record, relative_to):
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ValueError("source needs exactly path and sha256")
    path = Path(record["path"])
    path = (relative_to / path).resolve() if not path.is_absolute() else path.resolve()
    if fingerprint(path)["sha256"] != record["sha256"]:
        raise ValueError(f"source pin changed: {path}")
    return path


def historical_receipts(rundir, plan, terminal="simpleanalysis"):
    """Validate the data's actual ancestor receipts, not eligibility to rerun them.

    A reader may use a different Python environment. Recorded runtime bytes are
    authenticated by the receipt and all original executable/source files are
    rehashed. No comparison with this reader's runtime is made or implied.
    """
    state = load_execution(rundir)
    stages = {s["stage"]: s for s in plan["stages"]}
    if len(stages) != len(plan["stages"]):
        raise ValueError("duplicate native plan stage")
    receipts, visiting, bound_files = {}, set(), {}
    def visit(name):
        if name in visiting:
            raise ValueError("receipt dependency cycle")
        if name in receipts:
            return
        visiting.add(name)
        record = state["stages"].get(name)
        stage = stages.get(name)
        if not isinstance(record, dict) or not stage or record.get("status") != "succeeded":
            raise ValueError(f"missing successful source receipt: {name}")
        fields = ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")
        if digest({k: record[k] for k in fields}) != record.get("fingerprint"):
            raise ValueError(f"source receipt specification changed: {name}")
        if record["command"] != stage["command"] or record["outputs"] != stage["outputs"] or set(record["parents"]) != set(stage["depends_on"]):
            raise ValueError(f"source receipt differs from exact native plan: {name}")
        if Path(record["cwd"]).resolve() != Path(rundir).resolve():
            raise ValueError(f"source receipt changed native working directory: {name}")
        if not set(stage["inputs"]) <= set(record["inputs"]):
            raise ValueError(f"source receipt omits native plan inputs: {name}")
        if snapshot(rundir, record["inputs"]) != record["input_snapshot"] or snapshot(rundir, record["outputs"], outputs=True) != record["output_snapshot"]:
            raise ValueError(f"source receipt artifacts changed: {name}")
        if digest({k: record[k] for k in ("fingerprint", "output_snapshot")}) != record.get("receipt_sha256"):
            raise ValueError(f"source receipt digest changed: {name}")
        attempt = (Path(rundir) / record["attempt_record"]).resolve()
        if not attempt.is_relative_to(Path(rundir).resolve() / "logs/execution") or read_json(attempt) != record:
            raise ValueError(f"immutable attempt record differs: {name}")
        # Bind all file leaves, including generator/shower logs, executables and
        # large ancestor outputs. Do not pin the mutable current-state ledger:
        # an unrelated later fit stage may legitimately append to it.
        bound_files[str(attempt)] = fingerprint(attempt)["sha256"]
        for field in ["input_snapshot", "output_snapshot"]:
            for path, item in record[field].items():
                for leaf in item["files"]:
                    file = Path(path) if leaf["name"] == "." else Path(path) / leaf["name"]
                    key = str(file.resolve())
                    if key in bound_files and bound_files[key] != leaf["sha256"]:
                        raise ValueError("conflicting source hashes across ancestor receipts")
                    bound_files[key] = leaf["sha256"]
        for parent, expected in record["parents"].items():
            visit(parent)
            if receipts[parent]["receipt_sha256"] != expected:
                raise ValueError(f"source parent receipt changed: {name}")
        receipts[name] = {"receipt_sha256": record["receipt_sha256"], "runtime": record["runtime"],
                          "attempt_record": record["attempt_record"]}
        visiting.remove(name)
    visit(terminal)
    required = {"prepare", "madgraph", "unpack_lhe", "lhe_check", "pythia", "normalization", "delphes", "analysis", "simpleanalysis"}
    if not required <= set(receipts):
        raise ValueError("native production ancestor receipt chain is incomplete")
    return receipts, stages, bound_files


def card_without_run_variations(path):
    """Preserve all noncomment syntax except two explicitly parsed run fields."""
    result = []
    for raw in path.read_text().splitlines():
        text = re.split(r"[#!]", raw, maxsplit=1)[0].strip()
        if not text:
            continue
        if "=" in text and text.split("=", 1)[1].strip() in {"nevents", "iseed"}:
            continue
        result.append(text)
    return result


def shower_physics(path):
    assignments = card_assignments(path, "shower")
    if assignments.get("Random:setSeed", "").lower() != "on":
        raise ValueError("replicas require an explicit enabled shower seed")
    try:
        seed = int(assignments["Random:seed"])
    except (KeyError, ValueError) as exc:
        raise ValueError("replicas require an explicit numeric shower seed") from exc
    if not 0 < seed < 900000000:
        raise ValueError("shower seed must be explicit, positive and in Pythia range")
    # Compare unknown/nonassignment lines too: do not silently discard directives.
    physics = []
    for raw in path.read_text().splitlines():
        text = re.split(r"[#!]", raw, maxsplit=1)[0].strip()
        if not text:
            continue
        key = text.split("=", 1)[0].strip()
        if key not in {"Random:seed", "Main:numberOfEvents", "Beams:LHEF"}:
            physics.append(text)
    return physics, seed


def detector_physics(path):
    matches = re.findall(r"(?m)^\s*set\s+RandomSeed\s+(\d+)\s*(?:#.*)?$", path.read_text())
    if len(matches) != 1 or int(matches[0]) < 1:
        raise ValueError("replicas require exactly one explicit positive detector RandomSeed")
    # Exact card content outside the seed is required; Tcl substitutions/includes
    # cannot be casually normalized. Relative external includes are unsupported.
    if re.search(r"(?m)^\s*source\s", path.read_text()):
        raise ValueError("detector card includes need an explicit transitive source adapter")
    physics = re.sub(r"(?m)^\s*set\s+RandomSeed\s+\d+\s*(?:#.*)?$", "set RandomSeed <replica-seed>", path.read_text())
    return physics, int(matches[0])


def uniform_positive(values, name, tolerance=1e-10):
    import numpy as np
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.all(np.isfinite(array)) or not np.all(array > 0):
        raise ValueError(f"{name} must have uniform positive nominal weights; signed/zero weights unsupported in pooling v1")
    if not np.allclose(array, array[0], rtol=tolerance, atol=0):
        raise ValueError(f"{name} is importance-weighted/nonuniform; unsupported in pooling v1")
    return array


def lhe_nominal_weights(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    weights, header = [], False
    with opener(path, "rt") as stream:
        for raw in stream:
            line = raw.split("#", 1)[0].strip()
            if line == "<event>":
                header = True
            elif header and line:
                weights.append(float(line.split()[2]))
                header = False
    return uniform_positive(weights, "original LHE")


def unique_events(values, name):
    import numpy as np
    array = np.asarray(values)
    if array.ndim != 1 or array.dtype.kind not in "iu" or len(set(map(int, array))) != len(array):
        raise ValueError(f"{name} needs unique integer Event identifiers")
    return array.astype(np.int64)


def scalar_arrays(path):
    import uproot
    with uproot.open(path) as stream:
        values = stream["ntuple"].arrays(library="np")
    return {name: values[name] for name in values.dtype.names} if getattr(values, "dtype", None) is not None and values.dtype.names else dict(values)


def load_replica(record, base):
    import awkward as ak
    import numpy as np
    import uproot
    if not isinstance(record, dict) or set(record) != {"plan"}:
        raise ValueError("each replica must identify one pinned native plan")
    plan_path = pinned(record["plan"], base)
    plan = read_json(plan_path)
    if plan_hash(plan) != plan.get("plan_sha256") or Path(plan["plan_path"]).resolve() != plan_path:
        raise ValueError("native plan hash or location changed")
    root = Path(plan["rundir"]).resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError("native plan is outside its source run")
    if plan["capability"].get("preparation") != "explicit-cards" or plan["capability"].get("routine") != "EwkCompressed2018" or plan["capability"].get("model") != "slepton-bino" or plan.get("compressed_signal_model") != "full":
        raise ValueError("pooling v1 requires explicit-card full EwkCompressed2018 slepton replicas")
    sources = {str(plan_path): record["plan"]["sha256"]}
    for source in plan["sources"]:
        path = pinned(source, root)
        sources[str(path)] = source["sha256"]
    plan_sources = dict(sources)
    receipts, stages, receipt_files = historical_receipts(root, plan)
    sources.update(receipt_files)
    inputs = {key: Path(path).resolve() for key, path in plan["inputs"].items()}
    for path in [Path(plan["config"]).resolve(), *inputs.values()]:
        if str(path) not in sources:
            raise ValueError("native configuration/card lacks source pin")
    produced = validate_process_card(inputs["process_card"], "slepton-bino")
    masses = validate_param_card(inputs["param_card"], "slepton-bino", produced=produced)
    if masses != plan["expected_masses_gev"]:
        raise ValueError("source card masses differ from plan")
    run = card_assignments(inputs["run_card"])
    n = plan["nevents"]
    if type(n) is not int or type(plan["seed"]) is not int or n < 1 or int(run["nevents"]) != n or int(run["iseed"]) != plan["seed"] or not int(run["iseed"]) > 0:
        raise ValueError("source generated exposure or seed disagrees with run card")
    if run.get("ickkw") != "0" or run.get("use_syst", "").lower() not in {"false", ".false."}:
        raise ValueError("pooling v1 supports only unmerged unweighted LO")
    shower, shower_seed = shower_physics(inputs["shower_card"])
    detector, detector_seed = detector_physics(inputs["delphes_card"])
    cfg = copy.deepcopy(read_config(plan["config"]))
    cfg["madgraph"]["run"].pop("nevents"); cfg["madgraph"]["run"].pop("seed")
    cfg["ravel"]["native"].pop("inputs")
    physics = {"config_except_paths_seeds_exposure": cfg,
        "process_sha256": fingerprint(inputs["process_card"])["sha256"],
        "param_sha256": fingerprint(inputs["param_card"])["sha256"],
        "run_card_except_seed_exposure": card_without_run_variations(inputs["run_card"]),
        "shower_except_seed_exposure_path": shower, "detector_except_seed": detector,
        "masses": masses, "kfactor": plan["kfactor"], "energy_GeV": plan["ecms_gev"],
        "routine": plan["capability"]["routine"], "compressed_signal_model": "full"}
    physics["additional_input_sha256"] = {key: fingerprint(path)["sha256"] for key, path in inputs.items()
        if key not in {"process_card", "param_card", "run_card", "shower_card", "delphes_card"}}
    # All implementation/binary source hashes must match as well; card paths and
    # data paths vary per replica, while their physics is compared separately.
    excluded = {str(Path(plan["config"]).resolve()), *(str(p) for p in inputs.values())}
    physics["implementation_sources"] = sorted((Path(path).name, sha) for path, sha in plan_sources.items() if path not in excluded and path != str(plan_path))
    norm_path = Path(stages["normalization"]["outputs"][0])
    normalization = load_normalization(norm_path)
    if normalization["basis"] != "unmerged_lo_lhe" or normalization["generation"]["n_events"] != n or normalization["kfactor"] != plan["kfactor"]:
        raise ValueError("normalization exposure, correction or LO basis disagrees")
    lhe = Path(normalization["sources"][0]["path"])
    raw_lhe = lhe_nominal_weights(lhe)
    if len(raw_lhe) != n:
        raise ValueError("original LHE exposure differs")
    converted_path = Path(stages["analysis"]["outputs"][0])
    conversion_path = Path(str(converted_path) + ".normalization.json")
    conversion = read_json(conversion_path)
    if conversion.get("generation_reconciled") is not True or conversion.get("luminosity_applied") is not False:
        raise ValueError("converted ROOT lacks reconciled original weight evidence")
    if pinned(conversion["output"], root) != converted_path.resolve() or pinned(conversion["normalization"], root) != norm_path.resolve():
        raise ValueError("conversion binds different ROOT/normalization")
    for source in conversion["sources"]:
        pinned(source, root)
    detector_path = pinned(conversion["sources"][0], root)
    if detector_path != Path(stages["delphes"]["outputs"][0]).resolve():
        raise ValueError("converted ROOT binds a different detector source")
    with uproot.open(detector_path) as stream:
        raw_detector = ak.to_numpy(ak.flatten(stream["Delphes"]["Event.Weight"].array(), axis=None))
    raw_detector = uniform_positive(raw_detector, "detector ROOT", tolerance=2e-6)
    with uproot.open(converted_path) as stream:
        tree = stream["ntuple"]
        events = unique_events(tree["Event"].array(library="np"), "all-event ROOT")
        nominal = tree["mcWeights"].array()
        if not ak.all(ak.num(nominal) >= 1):
            raise ValueError("all-event ROOT lacks nominal weights")
        weights = uniform_positive(ak.to_numpy(nominal[:, 0]), "converted ROOT", tolerance=2e-6)
    if len(events) != n or len(weights) != n or len(raw_detector) != n:
        raise ValueError("original generated exposure differs from all-event ROOT counts")
    xs = normalization["applied_cross_section_pb"]
    if not math.isclose(math.fsum(weights), xs, rel_tol=2e-6) or not np.allclose(weights, raw_detector * xs / math.fsum(raw_detector), rtol=2e-6, atol=0):
        raise ValueError("ROOT nominal normalization does not reproduce applied cross section")
    for key, actual in [("raw", weight_summary(raw_detector)), ("normalized", weight_summary(weights))]:
        expected = conversion[key]
        for name in ["n_events", "negative_weights", "sumw", "sumw2"]:
            if not math.isclose(actual[name], expected[name], rel_tol=2e-6, abs_tol=0):
                raise ValueError("conversion moments differ from actual ROOT")
    if conversion["applied_cross_section_pb"] != xs:
        raise ValueError("conversion rate differs from native normalization")
    analysis_path = Path(stages["simpleanalysis"]["outputs"][0])
    arrays = scalar_arrays(analysis_path)
    from ravel.physics.native_simpleanalysis import sr_order, cr_order
    region_names = sr_order() + cr_order()
    if set(arrays) != {"Event", "eventWeight", "isee", "ismm", *region_names}:
        raise ValueError("analysis ROOT branch schema differs from full native signal model")
    ids = unique_events(arrays["Event"], "analysis ROOT")
    positions = {int(e): i for i, e in enumerate(events)}
    if any(int(e) not in positions for e in ids):
        raise ValueError("analysis Event is absent from original exposure")
    local_index = np.array([positions[int(e)] for e in ids], dtype=np.int64)
    if not np.array_equal(arrays["eventWeight"], weights[local_index]):
        raise ValueError("analysis weights differ from source event weights")
    for name in region_names:
        values = arrays[name]
        if values.ndim != 1 or len(values) != len(ids) or not np.all(np.isfinite(values)) or not np.all((values == 0) | (values == arrays["eventWeight"])):
            raise ValueError(f"region weight is neither zero nor its source event weight: {name}")
    for flag in ["isee", "ismm"]:
        if not np.all((arrays[flag] == 0) | (arrays[flag] == 1)):
            raise ValueError("invalid native flavor flag")
    if np.any((arrays["isee"] != 0) & (arrays["ismm"] != 0)):
        raise ValueError("native flavor flags overlap")
    for path in [norm_path, conversion_path, converted_path, detector_path, analysis_path, lhe]:
        sources[str(path.resolve())] = fingerprint(path)["sha256"]
    return {"plan": fingerprint(plan_path), "rundir": str(root), "sources": sources,
        "physics": physics, "original_generated_events": n, "normalized_cross_section_pb": xs,
        "normalization": fingerprint(norm_path), "lhe_sha256": fingerprint(lhe)["sha256"],
        "mg_seed": plan["seed"], "shower_seed": shower_seed, "detector_seed": detector_seed,
        "receipts": receipts, "analysis_root": fingerprint(analysis_path),
        "arrays": arrays, "original_row_index": local_index, "region_names": region_names}


def combine(replicas):
    """Calculate pooled moments from records validated by load_replica."""
    import numpy as np
    if len(replicas) < 2:
        raise ValueError("pooling needs at least two independent replicas")
    if any(r["physics"] != replicas[0]["physics"] for r in replicas):
        raise ValueError("replicas have different physics/cards/configuration/implementation; additive components are not replicas")
    for field in ["mg_seed", "shower_seed", "detector_seed", "lhe_sha256"]:
        if len({r[field] for r in replicas}) != len(replicas):
            raise ValueError(f"duplicate replica {field}; independence not established")
    for r in replicas:
        n = r["original_generated_events"]
        if type(n) is not int or n < 1 or len(r["arrays"]["Event"]) > n:
            raise ValueError("invalid original generated exposure")
        if not math.isfinite(r["normalized_cross_section_pb"]) or r["normalized_cross_section_pb"] <= 0:
            raise ValueError("invalid normalized cross section")
    total = sum(r["original_generated_events"] for r in replicas)
    if type(total) is not int or not 0 < total <= np.iinfo(np.int64).max:
        raise ValueError("unusable original generated exposure")
    arrays, offset, records = [], 0, []
    for i, r in enumerate(replicas):
        n = r["original_generated_events"]
        alpha = n / total
        a = {name: values.copy() for name, values in r["arrays"].items()}
        a["sourceEvent"] = a["Event"].astype(np.int64)
        a["replicaIndex"] = np.full(len(a["Event"]), i, dtype=np.int32)
        a["Event"] = r["original_row_index"] + offset
        for name in ["eventWeight", *r["region_names"]]:
            a[name] = a[name] * alpha
        arrays.append(a); offset += n
        record = {key: value for key, value in r.items() if key not in {"arrays", "original_row_index", "region_names", "physics", "sources"}}
        records.append({**record, "alpha": alpha, "retained_analysis_rows": len(a["Event"])})
    result = {name: np.concatenate([a[name] for a in arrays]) for name in arrays[0]}
    moments = {}
    for name in replicas[0]["region_names"]:
        values = result[name]
        sumw = math.fsum(map(float, values)); sumw2 = math.fsum(float(v)**2 for v in values)
        if not math.isfinite(sumw) or not math.isfinite(sumw2):
            raise ValueError("pooled moments overflow")
        moments[name] = {"sumw_pb": sumw, "sumw2_pb2": sumw2, "selected_events": int(np.count_nonzero(values)),
            "absolute_mc_error_pb": math.sqrt(sumw2) if sumw2 else None,
            "precision_status": "estimated-from-own-moments" if sumw2 else "zero-selected-precision-unresolved"}
    return result, {"schema_version": 1, "input_combination": "pool-independent-replicas",
        "estimator": "alpha_j = original_generated_N_j / sum(original_generated_N); pooled w_ji = alpha_j * normalized w_ji",
        "statistical_scope": "uniform-positive unmerged LO replicas only; sqrt(sumw2) is a Poissonized independent-event MC approximation, not exact fixed-N binomial variance; moments condition on recorded cross sections; generator integration uncertainty is separate",
        "original_generated_events": total, "retained_analysis_rows": len(result["Event"]),
        "normalized_cross_section_pb": math.fsum(r["normalized_cross_section_pb"] * record["alpha"] for r, record in zip(replicas, records)),
        "luminosity_applied": False, "physics": replicas[0]["physics"], "replicas": records,
        "detector_seed_policy": "distinct across independent replicas; common-random-number controls require a separate covariance-aware analysis",
        "moments": moments, "acceptance_certified": False}


def pool(manifest_path, out):
    manifest_path = Path(manifest_path).resolve()
    out = Path(out).absolute()
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError("pool output must be a new nonsymlink directory")
    manifest_pin = fingerprint(manifest_path)
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "input_combination", "replicas"} or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["input_combination"] != "pool-independent-replicas":
        raise ValueError("explicit independent-replica manifest required; additive or unspecified combinations rejected")
    if not isinstance(manifest["replicas"], list) or len(manifest["replicas"]) < 2:
        raise ValueError("at least two source-bound replicas required")
    replicas = [load_replica(record, manifest_path.parent) for record in manifest["replicas"]]
    for r in replicas:
        if out.resolve().is_relative_to(Path(r["rundir"])):
            raise ValueError("pooled output cannot modify a predecessor run")
    data, metadata = combine(replicas)
    sources = {manifest_pin["path"]: manifest_pin["sha256"]}
    for r in replicas:
        sources.update(r["sources"])
    if any(fingerprint(path)["sha256"] != sha for path, sha in sources.items()):
        raise ValueError("source changed during pooling")
    import uproot
    # Reserve the new directory exclusively; failures retain only marked evidence.
    out.mkdir(parents=True, exist_ok=False)
    temporary = out / "pooled.root.partial"
    try:
        with uproot.recreate(temporary) as stream:
            stream["ntuple"] = data
        check = scalar_arrays(temporary)
        import numpy as np
        if set(check) != set(data) or any(not np.array_equal(check[k], v) for k, v in data.items()):
            raise ValueError("pooled ROOT round trip changed data")
        metadata.update(input_manifest=manifest_pin, source_files=[{"path": p, "sha256": s} for p, s in sorted(sources.items())],
            output={"path": str((out/"pooled.root").resolve()), "sha256": fingerprint(temporary)["sha256"]},
            status="complete", output_roundtrip_verified=True)
        if any(fingerprint(path)["sha256"] != sha for path, sha in sources.items()):
            raise ValueError("source changed while writing pooled ROOT")
        # Serialize before publishing the final ROOT. A write failure cannot be
        # converted to a successful output by best-effort exception handling.
        with (out / "pooling.json").open("x") as stream:
            stream.write(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
        temporary.rename(out / "pooled.root")
    except BaseException as exc:
        (out / "FAILED.json").write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        raise
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True, help="NEW output directory")
    args = parser.parse_args(argv)
    result = pool(args.manifest, args.out)
    print(json.dumps({"status": result["status"], "original_generated_events": result["original_generated_events"], "replicas": len(result["replicas"]), "acceptance_certified": False}))


if __name__ == "__main__":
    main()
