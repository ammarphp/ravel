"""Source-bound calibrated-event projection through a supplied selection package."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

from ravel.workflow.state_io import atomic_json, _unique

MAX_BYTES, MAX_EVENTS, MAX_VARIATIONS = 128 * 1024 * 1024, 100_000, 128

from .analysis_packages import load_routine, PackageInputError, selected_attribute

def _selection(document):
    if not isinstance(document, dict) or 'analysis_package' not in document:
        raise PackageInputError('missing_analysis_package')
    path = _bound(document['analysis_package'], '.')
    routine = load_routine(path)
    if routine.ANALYSIS_PACKAGE['routine']['kind'] != 'calibrated':
        raise PackageInputError('unsupported_routine_interface')
    return routine

def __getattr__(name):
    return selected_attribute(name)


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(label + " requires exactly " + ", ".join(sorted(expected)))


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be nonempty text")
    return value


def _number(value, label, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + " must be finite")
    if nonnegative and value < 0 or positive and value <= 0:
        raise ValueError(label + " is outside its allowed range")
    return float(value)


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(label + " must be boolean")


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + " must be a nonnegative integer")


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _read(path, *, sha256=None):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("stau input exceeds byte limit")
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("stau source bytes changed during read: " + str(path))
    def reject(value):
        raise ValueError("nonfinite JSON constant " + value)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def _pin(pin):
    _keys(pin, ("path", "sha256"), "source pin")
    _text(pin["path"], "source path")
    if not isinstance(pin["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise ValueError("source digest must be SHA256")


def _bound(pin, base):
    from ravel.workflow.science import regular
    from ravel.workflow.execution import file_hash
    _pin(pin)
    path = regular(pin["path"], base)
    if file_hash(path) != pin["sha256"]:
        raise ValueError("stau source bytes changed: " + pin["path"])
    return path


def validate(task):
    _keys(task, ("input",), "stau task")
    _text(task["input"], "input path")
    return deepcopy(task)


def validate_document(document):
    selection = _selection(document)
    if "output" not in document:
        raise PackageInputError("missing_output")
    _keys(document, ("schema_version", "implementation", "dataset_id", "source", "grounding", "events", "response", "generation", "normalization", "eras", "era_assignment", "variations", "uncertainty_model", "analysis_package", "output"), "calibrated document")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1 or document["implementation"] != selection.IMPLEMENTATION:
        raise ValueError("unknown stau schema or implementation identity")
    for key in ("dataset_id", "source"):
        _text(document[key], key)
    _pin(document["events"])
    if not isinstance(document["grounding"], list) or not document["grounding"]:
        raise ValueError("source grounding is required")
    for pin in document["grounding"]:
        _pin(pin)
    response = document["response"]
    _keys(response, ("stage", "components", "evidence"), "response contract")
    if (response["stage"] != "calibrated_post_overlap_removal" or not isinstance(response["components"], dict)
            or set(response["components"]) != selection.RESPONSE_COMPONENTS):
        raise ValueError("all supplied calibrated response components are required")
    for description in response["components"].values():
        _text(description, "response semantics")
    if not isinstance(response["evidence"], list) or not response["evidence"]:
        raise ValueError("response evidence is required")
    for pin in response["evidence"]:
        _pin(pin)
    generation = document["generation"]
    selection.validate_generation(generation)
    eras = selection._eras(document["eras"])
    assignment = document["era_assignment"]
    _keys(assignment, ("kind", "seed"), "era assignment")
    if assignment["kind"] not in ("stable_hash", "luminosity_mixture"):
        raise ValueError("era assignment must be shard-stable or a deterministic luminosity mixture")
    _text(assignment["seed"], "era seed")
    norm = document["normalization"]
    _keys(norm, ("cross_section_pb", "cross_section_basis", "branching_ratio_factor", "filter_efficiency", "denominator_basis", "expected_sumw", "evidence"), "normalization")
    _number(norm["cross_section_pb"], "cross section", positive=True)
    if norm["cross_section_basis"] not in ("inclusive_production", "specified_decays"):
        raise ValueError("cross section basis must identify whether branching ratios are already included")
    for key in ("branching_ratio_factor", "filter_efficiency"):
        value = _number(norm[key], key, positive=True)
        if value > 1:
            raise ValueError(key + " must be at most one")
    if norm["cross_section_basis"] == "specified_decays" and norm["branching_ratio_factor"] != 1:
        raise ValueError("branching ratios must not be counted twice")
    if norm["denominator_basis"] not in ("before_filter", "after_filter"):
        raise ValueError("unknown denominator/filter basis")
    if norm["denominator_basis"] == "before_filter" and norm["filter_efficiency"] != 1:
        raise ValueError("before-filter denominator must not multiply filter efficiency again")
    if not isinstance(norm["evidence"], list) or not norm["evidence"]:
        raise ValueError("normalization evidence is required")
    for pin in norm["evidence"]:
        _pin(pin)
    variations = document["variations"]
    if not isinstance(variations, list) or len(variations) > MAX_VARIATIONS:
        raise ValueError("variations exceed admission bound")
    names, streams = [], ["nominal"]
    for variation in variations:
        _keys(variation, ("name", "up", "down", "normalization", "description"), "variation")
        for key in ("name", "up", "down", "description"):
            _text(variation[key], "variation " + key)
        if variation["normalization"] not in ("nominal_denominator", "own_denominator"):
            raise ValueError("variation normalization must be explicit")
        names.append(variation["name"])
        streams.extend([variation["up"], variation["down"]])
    if len(names) != len(set(names)) or len(streams) != len(set(streams)):
        raise ValueError("duplicate variation identity or state stream")
    _keys(norm["expected_sumw"], streams, "all-stream generator denominator witnesses")
    for value in norm["expected_sumw"].values():
        _number(value, "expected generator sumw")
    if document["uncertainty_model"] != "poissonized_independent_groups_conditional_denominator":
        raise ValueError("unsupported MC sampling model; covariance is not a signed-MC likelihood")
    output = document['output']
    if not isinstance(output, dict) or set(output) != {'prediction', 'contract', 'decisions', 'format'}:
        raise PackageInputError('missing_output')
    if output['format'] not in ('json', 'jsonl'):
        raise ValueError('projection format must be json or jsonl')
    if len(set(output[k] for k in ('prediction', 'contract', 'decisions'))) != 3:
        raise ValueError('output members must be distinct')
    for key in ('prediction', 'contract', 'decisions'):
        path = Path(output[key])
        if len(path.parts) != 1 or path.name in ('', '.', '..'):
            raise ValueError('output members must be simple filenames')
    return deepcopy(document)


def _load(task, base):
    from ravel.workflow.science import regular
    path = regular(validate(task)["input"], base)
    document = _read(path)
    if 'analysis_package' not in document:
        raise PackageInputError('missing_analysis_package')
    selected = _bound(document['analysis_package'], path.parent)
    document['analysis_package'] = {**document['analysis_package'], 'path': str(selected)}
    return path, validate_document(document)


def inputs(task, base):
    path, document = _load(task, base)
    pins = [document["analysis_package"], document["events"], *document["grounding"], *document["response"]["evidence"],
            *document["generation"]["evidence"], *document["normalization"]["evidence"]]
    selection = _selection(document)
    return sorted({path, *(_bound(pin, path.parent) for pin in pins),
                   *(Path(pin['path']) for pin in selection.ANALYSIS_PACKAGE['source_pins'])}, key=str)


def project(document, records):
    """Compute all-channel nominal/variation yields with group-level MC moments.

    Every generated record contributes to its declared generator denominator,
    including failed filters and analysis cuts. Absolute variation weights and
    complete alternate states are required; no nominal-state fallback exists.
    """
    document = validate_document(document)
    selection = _selection(document)
    CHANNELS = tuple(selection.sr_order())
    if not isinstance(records, list) or not 0 < len(records) <= MAX_EVENTS:
        raise ValueError("a complete bounded event census is required")
    eras = selection._eras(document["eras"])
    era_names = [era["name"] for era in eras]
    streams = list(document["normalization"]["expected_sumw"])
    total_lumi = math.fsum(era["luminosity_fb"] for era in eras)
    denoms, absdenoms = defaultdict(list), defaultdict(list)
    # Retain per-event values before summing to give stable order-independent
    # fsum arithmetic, including correlated signed subevents in each group.
    grouped = {stream: defaultdict(lambda: [[] for _ in CHANNELS]) for stream in streams}
    audit, seen, negative_weights = [], set(), 0
    nonnegative_weights = True
    for record in records:
        _keys(record, ("event_id", "group_id", "generator_filter_pass", "weights", "states"), "event record")
        for key in ("event_id", "group_id"):
            _text(record[key], key)
        if record["event_id"] in seen:
            raise ValueError("duplicate original event_id")
        seen.add(record["event_id"])
        _boolean(record["generator_filter_pass"], "generator filter decision")
        if document["normalization"]["denominator_basis"] == "after_filter" and not record["generator_filter_pass"]:
            raise ValueError("after-filter census cannot contain a rejected generator-filter record")
        _keys(record["weights"], streams, "absolute generator weights")
        _keys(record["states"], era_names, "all-era event states")
        for era_name in era_names:
            _keys(record["states"][era_name], streams, "all-stream event states")
        chosen = selection.stable_era(document["dataset_id"], record["group_id"], eras, document["era_assignment"]["seed"])
        row = {"event_id": record["event_id"], "group_id": record["group_id"], "assigned_era": chosen if document["era_assignment"]["kind"] == "stable_hash" else None,
               "generator_filter_pass": record["generator_filter_pass"], "streams": {}}
        negative_weights += record["weights"]["nominal"] < 0
        for stream in streams:
            weight = _number(record["weights"][stream], "generator weight")
            nonnegative_weights = nonnegative_weights and weight >= 0
            denoms[stream].append(weight)
            absdenoms[stream].append(abs(weight))
            contributions = [[] for _ in CHANNELS]
            decisions = {}
            for era in eras:
                state = record["states"][era["name"]][stream]
                if not record["generator_filter_pass"]:
                    if state is not None:
                        raise ValueError("failed generator-filter event must explicitly use null calibrated states")
                    continue
                # Validate also unselected hash eras: input completeness is not
                # allowed to depend on a random assignment or future repartition.
                decisions_for_era = selection.select_regions(state, era["trigger_epoch"])
                fraction = era["luminosity_fb"] / total_lumi if document["era_assignment"]["kind"] == "luminosity_mixture" else float(era["name"] == chosen)
                decisions[era["name"]] = decisions_for_era
                for index, channel in enumerate(CHANNELS):
                    contributions[index].append(weight * fraction * state["response_weights"][channel] * decisions_for_era[channel])
            values = [math.fsum(values) for values in contributions]
            for index, value in enumerate(values):
                grouped[stream][record["group_id"]][index].append(value)
            row["streams"][stream] = {"decisions": decisions, "weighted_contributions": dict(zip(CHANNELS, values))}
        audit.append(row)
    summed = {stream: math.fsum(values) for stream, values in denoms.items()}
    for stream, expected in document["normalization"]["expected_sumw"].items():
        if not math.isclose(summed[stream], expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("generator census sumw disagrees with normalization witness: " + stream)
    denominator_for = {"nominal": "nominal"}
    for variation in document["variations"]:
        for stream in (variation["up"], variation["down"]):
            denominator_for[stream] = stream if variation["normalization"] == "own_denominator" else "nominal"
    norm = document["normalization"]
    numerator = norm["cross_section_pb"] * 1000 * total_lumi * norm["branching_ratio_factor"] * norm["filter_efficiency"]
    predictions = {}
    for stream in streams:
        denominator = summed[denominator_for[stream]]
        if denominator <= 0:
            raise ValueError("physical cross-section normalization requires a positive generator denominator")
        scale = numerator / denominator
        groups = [[math.fsum(values) for values in grouped[stream][group]] for group in sorted(grouped[stream])]
        sums = [math.fsum(group[index] for group in groups) for index in range(len(CHANNELS))]
        covariance = [[scale**2 * math.fsum(group[i] * group[j] for group in groups) for j in range(len(CHANNELS))] for i in range(len(CHANNELS))]
        predictions[stream] = {"scale": scale, "denominator_stream": denominator_for[stream], "sumw": sums,
            "yields": [scale * value for value in sums], "mc_covariance": covariance,
            "mc_standard_errors": [math.sqrt(covariance[i][i]) for i in range(len(CHANNELS))]}
    variations = {variation["name"]: {"hi_data": predictions[variation["up"]]["yields"], "lo_data": predictions[variation["down"]]["yields"],
                                      "normalization": variation["normalization"]} for variation in document["variations"]}
    return {"schema_version": 1, "implementation": selection.IMPLEMENTATION, "channels": list(CHANNELS), "source": document["source"], "analysis_package": document["analysis_package"],
            "dataset_id": document["dataset_id"], "events": len(records), "groups": len(grouped["nominal"]),
            "negative_nominal_weights": negative_weights, "generator_sumw": summed,
            "generator_weight_model": "nonnegative" if nonnegative_weights else "signed",
            "generator_sum_absw": {key: math.fsum(value) for key, value in absdenoms.items()},
            "era_assignment": document["era_assignment"], "luminosity_fb": total_lumi,
            "predictions": predictions, "absolute_variations": variations,
            "template_ready_nonnegative": all(value >= 0 for prediction in predictions.values() for value in prediction["yields"]),
            "mc_likelihood_admitted": False, "event_audit": sorted(audit, key=lambda row: row["event_id"]),
            "physics_validated": False,
            "limitations": ["Response, overlap removal, trigger matching, top tagging, mT2 and generation/decay/filter semantics are supplied and source-bound, not detector-validated here.",
                "Group Poisson MC covariance is conditional on the supplied generator denominator; it is not a finite-MC likelihood or sparse/signed-MC inference prescription.",
                "No official benchmark systematics are copied to a new model. Full source-consistent modifier decomposition and inference admission are separate requirements.",
                "No same-event native detector comparison or withheld-model recasting validation is inferred from this projection."]}


def build_signal_template_from_projection(source_contract, prediction_binding, supplied_template, base="."):
    """Connect an actual projection to the modifier-aware published workspace.

    The caller supplies the entire source modifier decomposition, not another
    mass point's scaled systematics. Every normsys/histosys nuisance must have
    its total up/down prediction in the retained event projection. The checks
    below compare the product of normalization and absolute shape anchors with
    that total, and require the projected finite-MC errors. This bounded bridge
    refuses signed weights or non-diagonal channel MC covariance; neither can
    be silently turned into independent pyhf statistical modifiers.
    """
    from ravel.physics import signal_templates
    path = _bound(prediction_binding, base)
    prediction = _read(path, sha256=prediction_binding["sha256"])
    selection = _selection(prediction)
    CHANNELS = tuple(selection.sr_order())
    if prediction.get("implementation") != selection.IMPLEMENTATION or prediction.get("channels") != list(CHANNELS):
        raise ValueError("projection identity or complete channel order differs")
    if prediction.get("generator_weight_model") != "nonnegative":
        raise ValueError("signed-weight projection requires a justified signed finite-MC likelihood")
    nominal = prediction["predictions"]["nominal"]
    covariance = nominal["mc_covariance"]
    if any(covariance[i][j] != 0 for i in range(len(CHANNELS)) for j in range(len(CHANNELS)) if i != j):
        raise ValueError("cross-channel MC covariance cannot be dropped by the template bridge")
    template = signal_templates.validate_template(supplied_template)
    if {channel["name"] for channel in template["channels"]} != set(CHANNELS):
        raise ValueError("projection template requires the complete supplied channel population")
    variations = prediction["absolute_variations"]
    for channel in template["channels"]:
        index = CHANNELS.index(channel["name"])
        if len(channel["samples"]) != 1:
            raise ValueError("stau projection bridge requires one explicitly supplied signal sample per channel")
        sample = channel["samples"][0]
        if sample["data"] != [nominal["yields"][index]]:
            raise ValueError("template nominal differs from projected signal")
        provenance = sample["provenance"]
        if provenance["kind"] != "supplied_prediction" or prediction_binding not in provenance["evidence"]:
            raise ValueError("every template signal must bind this retained projection as supplied evidence")
        stat = sample["mc_stat"]
        if (stat["mode"] != "supplied" or stat["sumw"] != sample["data"]
                or stat["sumw2"] != [covariance[index][index]]):
            raise ValueError("template finite-MC moments differ from projected group moments")
        modifiers = {(modifier["name"], modifier["type"]): modifier["data"] for modifier in sample["modifiers"]}
        names = {name for name, kind in modifiers if kind in ("normsys", "histosys")}
        if names != set(variations):
            raise ValueError("every source signal nuisance requires complete event variation predictions")
        for name in names:
            normalization = modifiers.get((name, "normsys"), {"hi": 1, "lo": 1})
            shape = modifiers.get((name, "histosys"), {"hi_data": sample["data"], "lo_data": sample["data"]})
            for direction in ("hi", "lo"):
                total = normalization[direction] * shape[direction + "_data"][0]
                expected = variations[name][direction + "_data"][index]
                if not math.isclose(total, expected, rel_tol=1e-10, abs_tol=1e-12):
                    raise ValueError("normalization/shape anchor differs from total projected variation: " + name)
    return signal_templates.build_signal_template(source_contract, template, base)


def run(task, base, out):
    inputs(task, base)
    path, document = _load(task, base)
    records = _read(_bound(document["events"], path.parent), sha256=document["events"]["sha256"])
    prediction = project(document, records)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("stau projection output must be empty")
    selection = _selection(document)
    audit = prediction.pop("event_audit")
    output = document["output"]
    if output['format'] == 'json':
        atomic_json(out / output['prediction'], prediction)
    else:
        with (out / output['prediction']).open('x') as stream:
            for name, values in prediction['predictions'].items():
                stream.write(_compact({'stream': name, **values}).decode() + '\n')
    atomic_json(out / output["contract"], document)
    with (out / output["decisions"]).open("x") as stream:
        for row in audit:
            stream.write(_compact(row).decode() + "\n")
    return {"status": "passed", "physics_validated": False, "scope": "Supplied calibrated-event selection projection",
            "generated_events": 0, "prediction": output["prediction"], "contract": output["contract"], "event_decisions": output["decisions"],
            "channels": list(selection.sr_order()), "template_ready_nonnegative": prediction["template_ready_nonnegative"],
            "mc_likelihood_admitted": False, "limitations": prediction["limitations"]}


def project_contract(contract):
    """Project supplied populations for arbitrary named parameter points; no parameter inference."""
    for key in ('study_id', 'parameter_points', 'datasets', 'output'):
        if key not in contract:
            raise PackageInputError('missing_' + key)
    _text(contract['study_id'], 'study identity')
    points = contract['parameter_points']
    datasets = contract['datasets']
    if not isinstance(points, list) or not points or not isinstance(datasets, dict) or not datasets:
        raise PackageInputError('missing_parameter_population')
    output = contract['output']
    if not isinstance(output, dict) or output.get('format') not in ('json', 'jsonl') or not output.get('path'):
        raise PackageInputError('missing_output')
    predictions = []
    for point in points:
        _keys(point, ('parameters', 'dataset', 'document'), 'parameter point')
        if not isinstance(point['parameters'], dict) or point['dataset'] not in datasets:
            raise PackageInputError('missing_dataset')
        prediction = project(point['document'], datasets[point['dataset']])
        predictions.append({'parameters': deepcopy(point['parameters']), 'dataset': point['dataset'],
                            'prediction': prediction})
    result = {'study_id': contract['study_id'], 'points': predictions, 'physics_validated': False}
    with Path(output['path']).open('x') as stream:
        if output['format'] == 'json':
            stream.write(_compact(result).decode() + '\n')
        else:
            for row in predictions:
                stream.write(_compact({'study_id': result['study_id'], **row}).decode() + '\n')
    return result
