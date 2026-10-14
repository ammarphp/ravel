"""Source-bound paired normalized quantities using the existing moment engine.

Each original subevent must occur in every arm, including rejection and zero
weights. Arm-specific fills and weights become structurally zero-padded weight
streams in ``quantities``. Independent groups, not expanded arm rows, define
sampling units. This bounded adapter supports one fill per arm/subevent and
does not infer detector, integration, reference or nuisance uncertainty.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.physics import quantities
from ravel.workflow.state_io import atomic_json


MODELS = {"poissonized_independent_groups", "fixed_iid_groups"}
MAX_STREAMS, MAX_RAW_DIMENSIONS, MAX_CONTRASTS = 16, 128, 16
MAX_KERNEL_PRODUCTS, MAX_TOTAL_WITNESS_WORK = 8_000_000, 8_000_000


def resource_limits():
    """Adapter admission limits; checker limits are read from its actual source."""
    from ravel.validation import numerical_witness
    return {"artifact_bytes": numerical_witness.MAX_BYTES,
            "original_events": numerical_witness.MAX_ROWS, "bins": numerical_witness.MAX_CHANNELS,
            "witness_row_bin_squared": numerical_witness.MAX_WORK,
            "arm_weight_streams": MAX_STREAMS, "raw_moment_dimensions": MAX_RAW_DIMENSIONS,
            "contrasts": MAX_CONTRASTS, "kernel_group_products": MAX_KERNEL_PRODUCTS,
            "total_witness_row_bin_squared": MAX_TOTAL_WITNESS_WORK}


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _admit_bytes(raw, label):
    if len(raw) > resource_limits()["artifact_bytes"]:
        raise ValueError(label + " exceeds contrast artifact byte limit")
    return raw


def _read_bytes(path, *, compressed=False):
    opener = gzip.open if compressed else open
    with opener(path, "rb") as stream:
        raw = stream.read(resource_limits()["artifact_bytes"] + 1)
    return _admit_bytes(raw, "contrast input " + str(path))


def _json(raw):
    from ravel.workflow.state_io import _unique
    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def _admit_shape(document):
    """Check dimensions before the bin validator or covariance allocation."""
    limits = resource_limits()
    quantity, arms, comparisons = document["quantity"], document["arms"], document["contrasts"]
    if not isinstance(quantity, dict):
        raise ValueError("contrast quantity must be an object")
    bins, weights = quantity.get("bins"), quantity.get("weight_names")
    if not isinstance(bins, list) or not 0 < len(bins) <= limits["bins"]:
        raise ValueError("contrast bins exceed admission limit or are empty")
    if not isinstance(weights, list) or not weights:
        raise ValueError("contrast weight_names must be a nonempty list")
    if not isinstance(arms, list) or len(arms) < 2:
        raise ValueError("at least two contrast arms are required")
    streams = len(arms) * len(weights)
    if streams > MAX_STREAMS:
        raise ValueError("contrast arm-weight streams exceed admission limit")
    if streams * (len(bins) + 2) > MAX_RAW_DIMENSIONS:
        raise ValueError("contrast raw moment dimensions exceed admission limit")
    if not isinstance(comparisons, list) or not 0 < len(comparisons) <= MAX_CONTRASTS:
        raise ValueError("contrast count exceeds admission limit or is empty")
    _admit_bytes(_compact(document), "contrast document")


def _admit_work(document, census):
    """Bound both independent checker arithmetic and retained kernel products."""
    limits = resource_limits()
    count, bins = len(census["records"]), len(document["quantity"]["bins"])
    witness_work = count * bins * bins
    if witness_work > limits["witness_row_bin_squared"]:
        raise ValueError("contrast original-event bin-squared work exceeds checker admission limit")
    if witness_work * len(document["contrasts"]) > MAX_TOTAL_WITNESS_WORK:
        raise ValueError("contrast aggregate witness work exceeds admission limit")
    dimensions = len(document["arms"]) * len(document["quantity"]["weight_names"]) * (bins + 2)
    groups = len({row["group_id"] for row in census["records"]})
    # Structural zeros still occupy sparse moment indices in the existing
    # kernel. Bound its retained upper-triangle products conservatively.
    if groups * dimensions * (dimensions + 1) // 2 > MAX_KERNEL_PRODUCTS:
        raise ValueError("contrast retained group-product work exceeds admission limit")


def validate(task):
    """Validate the supervised task. Nested paths are relative to its input file."""
    quantities._keys(task, ("input",), label="event contrast task")
    quantities._text(task["input"], "contrast input path")
    return json.loads(json.dumps(task, allow_nan=False))


def _pin(value):
    quantities._keys(value, ("path", "sha256"), label="source binding")
    quantities._text(value["path"], "source path")
    if not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise ValueError("source sha256 must be lowercase hexadecimal")


def _file(value, base):
    from ravel.workflow.science import regular
    return regular(value, base)


def _bound(value, base):
    _pin(value)
    path = _file(value["path"], base)
    from ravel.workflow.execution import file_hash
    if file_hash(path) != value["sha256"]:
        raise ValueError("contrast source bytes changed: " + value["path"])
    return path


def validate_document(document):
    """Validate explicit arm, normalization and sampling semantics."""
    quantities._keys(document, ("schema_version", "source", "original_artifacts", "census", "coupling",
                               "quantity", "arms", "contrasts", "uncertainty_model"), label="contrast input")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported contrast schema_version")
    _admit_shape(document)
    quantities._text(document["source"], "contrast source")
    if not isinstance(document["original_artifacts"], list) or not document["original_artifacts"]:
        raise ValueError("original source artifact bindings are required")
    for pin in [document["census"], *document["original_artifacts"]]:
        _pin(pin)
    coupling = document["coupling"]
    quantities._keys(coupling, ("kind", "evidence"), label="event coupling")
    if coupling["kind"] != "same_source_groups":
        raise ValueError("this adapter requires declared same-source group pairing and a complete identity join")
    quantities._text(coupling["evidence"], "coupling evidence")
    contract = quantities.validate(document["quantity"])
    if contract["normalization"]["kind"] != "normalized":
        raise ValueError("this contrast adapter requires explicit in_range or all_events ratio normalization")
    if any("::" in name for name in contract["weight_names"]):
        raise ValueError("base weight names cannot contain reserved arm separator ::")
    if document["uncertainty_model"] not in MODELS:
        raise ValueError("unknown contrast sampling uncertainty_model")
    arms = document["arms"]
    if not isinstance(arms, list) or len(arms) < 2:
        raise ValueError("at least two contrast arms are required")
    names = []
    for arm in arms:
        quantities._keys(arm, ("name", "records"), label="contrast arm")
        name = quantities._text(arm["name"], "arm name")
        if "::" in name:
            raise ValueError("arm name cannot contain reserved separator ::")
        names.append(name)
        _pin(arm["records"])
    quantities._unique(names, "arm names")
    contrasts = document["contrasts"]
    if not isinstance(contrasts, list) or not contrasts:
        raise ValueError("at least one explicit contrast is required")
    ids = []
    for contrast in contrasts:
        quantities._keys(contrast, ("id", "baseline", "candidate"), label="contrast")
        ident = quantities._text(contrast["id"], "contrast id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ident):
            raise ValueError("contrast id must be a safe filename identifier")
        ids.append(ident)
        for label in ("baseline", "candidate"):
            stream = contrast[label]
            quantities._keys(stream, ("arm", "weight"), label="contrast stream")
            if stream["arm"] not in names or stream["weight"] not in contract["weight_names"]:
                raise ValueError("contrast refers to an undeclared arm or weight")
        if contrast["baseline"] == contrast["candidate"]:
            raise ValueError("contrast must compare distinct arm/weight streams")
    quantities._unique(ids, "contrast ids")
    return json.loads(json.dumps(document, allow_nan=False))


def _load(task, base_dir):
    task = validate(task)
    path = _file(task["input"], base_dir)
    return path, validate_document(_json(_read_bytes(path)))


def inputs(task, base_dir):
    """Return every source file the existing supervisor must bind before approval."""
    path, document = _load(task, base_dir)
    pins = [document["census"], *document["original_artifacts"],
            *[arm["records"] for arm in document["arms"]]]
    from ravel.validation import numerical_witness
    checker = Path(numerical_witness.__file__).resolve()
    return sorted({path, checker, *[_bound(pin, path.parent) for pin in pins]}, key=str)


def _rows(path):
    raw = _read_bytes(path, compressed=path.suffix == ".gz")
    if path.suffix == ".json":
        rows = _json(raw)
        if not isinstance(rows, list):
            raise ValueError("arm JSON input must be an array of complete event records")
        return rows
    return [_json(line) for line in raw.splitlines() if line.strip()]


def validate_census(census):
    quantities._keys(census, ("schema_version", "kind", "records"), label="original event census")
    if type(census["schema_version"]) is not int or census["schema_version"] != 1 or census["kind"] != "original_event_census":
        raise ValueError("unsupported original event census")
    if not isinstance(census["records"], list) or not census["records"]:
        raise ValueError("complete nonempty original event census is required")
    if len(census["records"]) > resource_limits()["original_events"]:
        raise ValueError("original census rows exceed checker admission limit")
    _admit_bytes(_compact(census), "original census")
    seen, shards = set(), {}
    for row in census["records"]:
        quantities._keys(row, ("event_id", "group_id", "shard_id"), label="original census record")
        for key in row:
            quantities._text(row[key], "original " + key)
        if row["event_id"] in seen:
            raise ValueError("duplicate original event_id")
        seen.add(row["event_id"])
        if row["group_id"] in shards and shards[row["group_id"]] != row["shard_id"]:
            raise ValueError("original correlated group spans independent shards")
        shards[row["group_id"]] = row["shard_id"]
    return json.loads(json.dumps(census, allow_nan=False))


def stream_name(arm, weight):
    return arm + "::" + weight


def assemble(document, census, arm_records):
    """Join the exact source×arm census and encode structural zeros deliberately.

    ``arm_records`` maps every declared arm to complete ordinary quantity rows.
    No missing event, arm or weight is imputed. Returns a quantity contract,
    derived records and the original-row lookup used by the witness export.
    """
    document, census = validate_document(document), validate_census(census)
    _admit_work(document, census)
    arms = [arm["name"] for arm in document["arms"]]
    if not isinstance(arm_records, dict) or set(arm_records) != set(arms):
        raise ValueError("missing or extra arm population")
    source = {row["event_id"]: row for row in census["records"]}
    weight_names = document["quantity"]["weight_names"]
    lookup = {}
    for arm in arms:
        if not isinstance(arm_records[arm], list) or len(arm_records[arm]) != len(source):
            raise ValueError("arm must contain exactly the original census row count: " + arm)
        lookup[arm] = {}
        for row in arm_records[arm]:
            quantities._keys(row, ("event_id", "group_id", "shard_id", "weights", "fills"), label="arm event")
            event_id = quantities._text(row["event_id"], "arm event_id")
            if event_id not in source or event_id in lookup[arm]:
                raise ValueError("unknown or duplicate original event in arm " + arm)
            if any(row[key] != source[event_id][key] for key in ("group_id", "shard_id")):
                raise ValueError("arm changed original group/shard identity")
            quantities._keys(row["weights"], weight_names, label="complete arm weights")
            for value in row["weights"].values():
                quantities._number(value, "arm weight")
            if not isinstance(row["fills"], list) or len(row["fills"]) > 1:
                raise ValueError("paired normalized P1 requires at most one fill per original subevent and arm")
            for fill in row["fills"]:
                if not isinstance(fill, list) or len(fill) != len(document["quantity"]["axes"]):
                    raise ValueError("fill dimensionality does not match axes")
                for value in fill:
                    quantities._number(value, "fill coordinate")
            lookup[arm][event_id] = row
        if set(lookup[arm]) != set(source):
            raise ValueError("arm omits original events, including rejected events: " + arm)
    contract = json.loads(json.dumps(document["quantity"], allow_nan=False))
    contract["weight_names"] = [stream_name(arm, weight) for arm in arms for weight in weight_names]
    records = []
    for original in census["records"]:
        event_id = original["event_id"]
        for arm in arms:
            row = lookup[arm][event_id]
            weights = {stream_name(other, weight): row["weights"][weight] if arm == other else 0.0
                       for other in arms for weight in weight_names}
            records.append({"event_id": json.dumps([event_id, arm], separators=(",", ":")),
                            "group_id": original["group_id"], "shard_id": original["shard_id"],
                            "weights": weights, "fills": row["fills"]})
    return contract, records, lookup


def _contribution(row, contract, weight):
    """Original raw integrated numerator and denominator, before density scaling."""
    bins = [0] * len(contract["bins"])
    for fill in row["fills"]:
        index = next((i for i, cell in enumerate(contract["bins"])
                      if all(lo <= x < hi for x, lo, hi in zip(fill, cell["low"], cell["high"]))), None)
        if index is not None:
            bins[index] += row["weights"][weight]
    denominator = math.fsum(bins) if contract["normalization"]["scope"] == "in_range" else row["weights"][weight]
    return {"bins": bins, "denominator": denominator}


def witness_payload(document, census, lookup, contrast):
    """Original-row payload for the separate exact-rational numerical checker."""
    contract = document["quantity"]
    baseline, candidate = contrast["baseline"], contrast["candidate"]
    census_bytes = json.dumps(census, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"schema_version": 1, "kind": "paired_normalized_rows",
            "basis": {"quantity": "paired_normalized_quantity", "unit": quantities._unit(contract),
                      "normalization": contract["normalization"]["scope"], "role": "nominal",
                      "channels": [cell["id"] for cell in contract["bins"]],
                      "checked_weight_stream": stream_name(**baseline) + "->" + stream_name(**candidate),
                      "representation": contract["representation"],
                      "bin_volumes": quantities.validate_binning(contract["axes"], contract["bins"])},
            "uncertainty_model": document["uncertainty_model"],
            "original_source_sha256": hashlib.sha256(census_bytes).hexdigest(),
            "exposure": {"original_events": len(census["records"]), "derived_records": 2 * len(census["records"])},
            "records": [{**original,
                         "baseline": _contribution(lookup[baseline["arm"]][original["event_id"]], contract, baseline["weight"]),
                         "candidate": _contribution(lookup[candidate["arm"]][original["event_id"]], contract, candidate["weight"])}
                        for original in census["records"]]}


def calculate(document, census, arm_records):
    """Calculate all joint arm moments and specified paired ratio contrasts."""
    document, census = validate_document(document), validate_census(census)
    contract, records, lookup = assemble(document, census, arm_records)
    # Admit complete original-row witnesses before the moment kernel retains
    # group products or allocates its covariance matrices.
    witnesses = {}
    for item in document["contrasts"]:
        payload = witness_payload(document, census, lookup, item)
        _admit_bytes(_compact(payload), "paired original-row witness")
        witnesses[item["id"]] = payload
    result = quantities.calculate(contract, records)
    groups = len(result["state"]["group_ids"])
    correction = 1.0
    if document["uncertainty_model"] == "fixed_iid_groups":
        if groups < 2:
            raise ValueError("fixed_iid_groups covariance requires at least two independent groups")
        correction = groups / (groups - 1)
    # Every normalized stream is homogeneous of degree zero. J T = 0, so the
    # fixed-iid centered total covariance projects to G/(G-1) times J Q J^T.
    joint = [[quantities._number(value * correction, "corrected covariance") for value in row]
             for row in result["covariance"]]
    denominators = {}
    for name, raw in result["denominators"].items():
        total, second = raw["sumw"], raw["sumw2"]
        variance = second
        if document["uncertainty_model"] == "fixed_iid_groups":
            centered = math.fsum((second, -total * (total / groups)))
            if centered < -1e-12 * max(second, 1e-300):
                raise ValueError("negative fixed-group denominator variance")
            variance = quantities._number(correction * max(0.0, centered), "denominator sampling variance")
        relative_error = math.sqrt(variance) / total
        denominators[name] = {"sumw": total, "raw_group_second_moment": second,
                              "sampling_variance": variance, "relative_standard_error": relative_error,
                              "uncertainty_model": document["uncertainty_model"],
                              "precision_status": "poorly_determined_denominator_first_order_precision_unresolved"
                                                  if relative_error >= 1 else "first_order_denominator_moment_available"}
    n = len(contract["bins"])
    contrasts = []
    for contrast in document["contrasts"]:
        before, after = (stream_name(**contrast[label]) for label in ("baseline", "candidate"))
        a, b = (contract["weight_names"].index(name) * n for name in (before, after))
        baseline, candidate = result["values"][before], result["values"][after]
        covariance = [[math.fsum((joint[a+i][a+j], joint[b+i][b+j], -joint[a+i][b+j], -joint[b+i][a+j]))
                       for j in range(n)] for i in range(n)]
        for i in range(n):
            scale = math.fsum(abs(joint[k][q]) for k in (a+i, b+i) for q in (a+i, b+i))
            if covariance[i][i] < -1e-12 * max(scale, 1e-300):
                raise ValueError("negative paired contrast variance")
            covariance[i][i] = max(0.0, covariance[i][i])
        precision = []
        for i in range(n):
            states = {}
            for name, offset, values in ((before, a, baseline), (after, b, candidate)):
                raw_offset = contract["weight_names"].index(name) * (n + 2)
                moment = result["state"]["second_moment"][raw_offset+i][raw_offset+i]
                states[name] = ("zero_selected_precision_unresolved" if values[i] == 0 and moment == 0
                                else "signed_cancellation_relative_precision_unresolved" if values[i] == 0
                                else "poorly_determined_denominator_first_order_precision_unresolved"
                                if denominators[name]["relative_standard_error"] >= 1
                                else "first_order_moment_available")
            precision.append({"bin_id": contract["bins"][i]["id"], "arms": states})
        contrasts.append({"id": contrast["id"], "baseline_stream": before, "candidate_stream": after,
                          "baseline": baseline, "candidate": candidate,
                          "difference": [math.fsum((y, -x)) for x, y in zip(baseline, candidate)],
                          "baseline_covariance": [row[a:a+n] for row in joint[a:a+n]],
                          "candidate_covariance": [row[b:b+n] for row in joint[b:b+n]],
                          "baseline_candidate_covariance": [row[b:b+n] for row in joint[a:a+n]],
                          "covariance": covariance, "precision": precision,
                          "denominators": {before: denominators[before], after: denominators[after]}})
    delivered = {"schema_version": 1, "kind": "coupled_event_contrast", "status": "passed",
                 "physics_validated": False, "source": document["source"], "coupling": document["coupling"],
                 "source_events": len(census["records"]), "derived_records": len(records), "independent_groups": groups,
                 "arm_names": [arm["name"] for arm in document["arms"]], "weight_names": document["quantity"]["weight_names"],
                 "structural_zero_policy": "Only declared off-arm streams are zero; every source event occurs in every arm.",
                 "quantity": document["quantity"], "unit": result["unit"], "bin_ids": result["bin_ids"],
                 "bin_volumes": result["bin_volumes"], "covariance_order": result["covariance_order"],
                 "joint_covariance": joint, "uncertainty_model": document["uncertainty_model"],
                 "kernel_uncertainty_model": "poissonized_independent_groups",
                 "fixed_group_correction": correction, "contrasts": contrasts,
                 "resource_limits": resource_limits(),
                 "normalization_meaning": "unit area over finite exclusive fills" if contract["normalization"]["scope"] == "in_range"
                                            else "quantity per weighted input event; area need not be one",
                 "scope": "Source-bound complete paired arm ratios with conditional independent-group MC covariance",
                 "limitations": ["First-order ratio covariance has no coverage or paper-reproduction claim.",
                                 "Source lineage and physical coupling are declared and bound, not detector calibration.",
                                 "No reference, integration, theory, detector or shared nuisance covariance is inferred.",
                                 "Zero selected contribution does not provide an upper bound on unseen acceptance.",
                                 "Positive but poorly determined signed denominators can invalidate first-order precision.",
                                 "Fixed-iid covariance, when requested, assumes iid independent groups; group count is not arm-row count."]}
    return {"result": delivered, "quantities": result, "witnesses": witnesses, "census": census}


def run(task, base_dir, outdir):
    """Execute the bound supplied-data operation; never generate events."""
    path, document = _load(task, base_dir)
    bound = inputs(task, base_dir)
    census_path = _bound(document["census"], path.parent)
    census = validate_census(_json(_read_bytes(census_path)))
    _admit_work(document, census)
    arms = {arm["name"]: _rows(_bound(arm["records"], path.parent)) for arm in document["arms"]}
    calculation = calculate(document, census, arms)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "contrast-quantities.json", calculation["quantities"])
    # The independent checker authenticates these exact complete census bytes.
    census_bytes = json.dumps(calculation["census"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with (out / "contrast-source-census.json").open("xb") as stream:
        stream.write(census_bytes)
    witness_files = {}
    receipts = {}
    from ravel.validation import numerical_witness
    checker_sha256 = numerical_witness.checker_sha256()
    by_id = {contrast["id"]: contrast for contrast in calculation["result"]["contrasts"]}
    for ident, payload in calculation["witnesses"].items():
        name = "contrast-witness-" + ident + ".json"
        input_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        with (out / name).open("xb") as stream:
            stream.write(input_bytes)
        witness_files[ident] = name
        contrast = by_id[ident]
        # Construct the numerical claim from PRODUCER outputs. The checker
        # derives its reference independently from original contribution rows.
        claim = {"schema_version": 1, "kind": "paired_normalized_moments", "status": "computed",
                 "basis": payload["basis"], "uncertainty_model": payload["uncertainty_model"],
                 "exposure": {**payload["exposure"], "independent_groups": calculation["result"]["independent_groups"]},
                 "denominators": {"baseline": contrast["denominators"][contrast["baseline_stream"]]["sumw"],
                                  "candidate": contrast["denominators"][contrast["candidate_stream"]]["sumw"]},
                 "values": {key: contrast[key] for key in ("baseline", "candidate", "difference")},
                 "covariance": {"baseline": contrast["baseline_covariance"], "candidate": contrast["candidate_covariance"],
                                "cross": contrast["baseline_candidate_covariance"], "difference": contrast["covariance"]},
                 "physics_validated": False, "arithmetic_verified": False}
        claim_bytes = json.dumps(claim, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        with (out / ("contrast-claim-" + ident + ".json")).open("xb") as stream:
            stream.write(claim_bytes)
        receipt = numerical_witness.verify(input_bytes, claim_bytes, expected_checker_sha256=checker_sha256,
                   expected_input_sha256=hashlib.sha256(input_bytes).hexdigest(),
                   expected_output_sha256=hashlib.sha256(claim_bytes).hexdigest(),
                   original_source_bytes=census_bytes,
                   expected_original_source_sha256=hashlib.sha256(census_bytes).hexdigest(),
                   atol="1e-14", rtol="1e-12")
        atomic_json(out / ("contrast-verification-" + ident + ".json"), receipt)
        receipts[ident] = receipt
    from ravel.workflow.execution import file_hash
    result = calculation["result"]
    checked = all(receipt["arithmetic_verified"] for receipt in receipts.values())
    result.update(status="passed" if checked else "failed",
                  quantities="contrast-quantities.json", source_census="contrast-source-census.json",
                  witness_inputs=witness_files, independent_witness_status="verified" if checked else "failed",
                  witness_receipts=receipts,
                  required_checks=[{"id": "complete_source_arm_census", "status": "passed"},
                                   {"id": "independent_original_row_arithmetic", "status": "passed" if checked else "failed"}],
                  input_bindings=[{"path": str(item), "sha256": file_hash(item)} for item in bound])
    # Recheck external bindings after arithmetic; changed sources never deliver.
    inputs(task, base_dir)
    atomic_json(out / "contrast-result.json", result)
    return result
