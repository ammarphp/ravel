"""Source-bound, complete SR/CR signal templates for published pyhf models.

The supplied nominal and absolute variation arrays are consumed verbatim. The
builder never transports another signal point's uncertainty by scaling it. A
published identity template is an engineering control, not a detector recast.
New predictions require byte-bound evidence and explicit finite-MC treatment.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

from ravel.workflow.release_registry import lazy_module
from ravel.validation import core as validation_core
published = lazy_module('ravel.physics.published_model')

MAX_TEMPLATE_BYTES = 16 * 1024 * 1024
SCOPE = "source-bound supplied signal templates; no detector, uncertainty or coverage certification"
MODIFIER_SETTINGS = {"normsys": {"interpcode": "code4"}, "histosys": {"interpcode": "code4p"}}


def _digest(value):
    return hashlib.sha256(published._compact(value)).hexdigest()


def _keys(value, required, optional=(), *, label):
    """Preserve adapter wording while sharing mechanical object validation."""
    message = label + " requires exactly " + ", ".join(required)
    if optional:
        message += " plus optional " + ", ".join(optional)
    validation_core.closed_object(dict(value) if isinstance(value, dict) else value,
                                  required, optional, field=label, message=message)


def _version(document, label):
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported " + label + " schema_version")


def _pin(pin):
    from ravel.validation.core import validate_pin
    validate_pin(pin, field='source binding')


def _pins(pins, label, *, nonempty=False):
    if not isinstance(pins, list) or (nonempty and not pins):
        raise ValueError(label + " requires a list of byte-bound evidence")
    for pin in pins:
        _pin(pin)


def _vector(values, bins, label):
    if not isinstance(values, list) or len(values) != bins or not values:
        validation_core.fail(label, values, f'nonempty list with {bins} channel bins',
                             message=label + " does not match the channel bin count")
    for index, value in enumerate(values):
        try:
            validation_core.finite_number(value, field=f'{label}[{index}]', minimum=0)
        except ValueError:
            validation_core.fail(f'{label}[{index}]', value, 'finite nonnegative number',
                                 message=label + " must be finite nonnegative numbers")


def _modifiers(sample, bins, poi):
    """Validate absolute anchors without ratios, including zero nominal bins."""
    modifiers = sample["modifiers"]
    if not isinstance(modifiers, list):
        raise ValueError("sample modifiers must be a list")
    pairs = set()
    for modifier in modifiers:
        _keys(modifier, ("name", "type", "data"), label="signal modifier")
        name = published._text(modifier["name"], "modifier name")
        kind = modifier["type"]
        if kind not in ("normfactor", "lumi", "normsys", "histosys", "staterror", "shapesys", "shapefactor"):
            raise ValueError("unsupported pyhf modifier type")
        pair = name, kind
        if pair in pairs:
            raise ValueError("duplicate signal modifier name/type")
        pairs.add(pair)
        data = modifier["data"]
        if kind in ("normfactor", "lumi", "shapefactor"):
            if data is not None:
                raise ValueError(kind + " requires null modifier data")
        elif kind == "normsys":
            _keys(data, ("hi", "lo"), label="normsys")
            for anchor, value in data.items():
                try:
                    validation_core.finite_number(value, field=f'normsys.{anchor}', minimum=0)
                    if value == 0:
                        raise ValueError('zero anchor')
                except ValueError:
                    validation_core.fail(f'normsys.{anchor}', value, 'finite positive factor',
                                         message="normsys anchors must be finite positive factors")
        elif kind == "histosys":
            _keys(data, ("hi_data", "lo_data"), label="absolute histosys")
            _vector(data["hi_data"], bins, "absolute histosys high anchor")
            _vector(data["lo_data"], bins, "absolute histosys low anchor")
        else:
            _vector(data, bins, kind + " absolute MC error")
    if sum(m["name"] == poi and m["type"] == "normfactor" for m in modifiers) != 1:
        raise ValueError("every signal sample needs exactly one measurement POI normfactor")
    return pairs


def validate(task):
    _keys(task, ("input",), ("operation",), label="signal-template task")
    published._text(task["input"], "signal-template input path")
    if task.get("operation", "inference") not in ("compile", "inference"):
        raise ValueError("signal-template operation must be compile or inference")
    return deepcopy(task)


def validate_document(document):
    """Bridge files pin the ordinary published input and a separate prediction."""
    _keys(document, ("schema_version", "published_model", "template"), label="signal-template bridge")
    _version(document, "signal-template bridge")
    _pin(document["published_model"])
    _pin(document["template"])
    return deepcopy(document)


def validate_template(template):
    _keys(template, ("schema_version", "template_id", "source_workspace_sha256",
                               "modifier_settings", "channels", "grounding"), label="signal template")
    _version(template, "signal template")
    published._text(template["template_id"], "template identity")
    published._sha(template["source_workspace_sha256"], "source workspace digest")
    # The admitted settings are the same as the published-model adapter. Other
    # interpolation families require their own validated inference contract.
    if template["modifier_settings"] != MODIFIER_SETTINGS:
        raise ValueError("signal template changes the admitted source interpolation settings")
    _pins(template["grounding"], "template grounding")
    channels = template["channels"]
    if not isinstance(channels, list) or not channels:
        raise ValueError("complete channel templates are required")
    names = set()
    for channel in channels:
        _keys(channel, ("name", "samples"), ("source_absent",), label="template channel")
        name = published._text(channel["name"], "channel name")
        if name in names:
            raise ValueError("duplicate template channel")
        names.add(name)
        if not isinstance(channel["samples"], list):
            raise ValueError("each fitted SR/CR channel requires an explicit signal sample")
        if "source_absent" in channel and channel["source_absent"] is not True:
            raise ValueError("source_absent must be explicitly true")
        if not channel["samples"] and channel.get("source_absent") is not True:
            raise ValueError("each fitted SR/CR channel requires an explicit signal sample")
        if channel["samples"] and "source_absent" in channel:
            raise ValueError("a predicted channel cannot be declared source_absent")
        sample_names = set()
        for sample in channel["samples"]:
            _keys(sample, ("name", "data", "modifiers", "provenance", "mc_stat"),
                            ("prediction", "prediction_requirements"), label="template sample")
            if ('prediction' in sample) != ('prediction_requirements' in sample):
                raise ValueError('prediction pin and consumer quantity requirements must be supplied together')
            if "prediction" in sample:
                _pin(sample["prediction"])
            name = published._text(sample["name"], "signal sample name")
            if name in sample_names:
                raise ValueError("duplicate template sample")
            sample_names.add(name)
            provenance = sample["provenance"]
            _keys(provenance, ("kind", "description", "evidence", "normalization_shape"), label="template provenance")
            if provenance["kind"] not in ("source_identity", "supplied_prediction"):
                raise ValueError("unsupported template provenance kind")
            published._text(provenance["description"], "prediction provenance")
            _pins(provenance["evidence"], "prediction provenance", nonempty=provenance["kind"] == "supplied_prediction")
            if provenance["normalization_shape"] != "source_decomposition":
                raise ValueError("normalization/shape decomposition must be explicit")
            stat = sample["mc_stat"]
            _keys(stat, ("mode", "description"), ("weight_model", "sumw", "sumw2"), label="MC-stat treatment")
            published._text(stat["description"], "MC-stat description")
            if stat["mode"] == "source_preserved":
                if set(stat) != {"mode", "description"}:
                    raise ValueError("source-preserved MC-stat treatment cannot replace MC moments")
            elif stat["mode"] == "supplied":
                if set(stat) != {"mode", "description", "weight_model", "sumw", "sumw2"}:
                    raise ValueError("supplied MC statistics require weight_model, sumw and sumw2")
                if stat["weight_model"] != "nonnegative":
                    raise ValueError("signed/cancelling MC needs a separately justified finite-MC likelihood")
            else:
                raise ValueError("MC statistics must be source_preserved or supplied")
    return deepcopy(template)


@dataclass(frozen=True)
class SignalTemplateContract:
    """Immutable source identity and distinct template/workspace identity."""
    manifest_json: bytes
    workspace_json: bytes
    patch_json: bytes

    def manifest(self):
        return published._json(self.manifest_json)

    def workspace(self):
        return published._json(self.workspace_json)

    def patch(self):
        return published._json(self.patch_json)


def build_signal_template(source_contract, template, base="."):
    """Replace only admitted signal samples; return a fit-consumable workspace.

    Every channel and every original signal modifier name/type is mandatory.
    Source omissions cannot be promoted to zero acceptance. The current bridge
    requires a published all-channel signal basis for new predictions. Official
    identity witnesses may preserve explicitly absent channels as unknown.
    Prediction evidence is pinned here, but its detector response and uncertainty
    validity need scientific review.
    """
    template = validate_template(template)
    source = source_contract.manifest()
    if template["source_workspace_sha256"] != source["workspace_compact_sha256"]:
        raise ValueError("prediction source workspace identity differs")
    for pin in template["grounding"]:
        published._bound_path(pin, base, published.MAX_MEMBER_BYTES)
    channels = {channel["name"]: channel for channel in template["channels"]}
    if set(channels) != set(source["channel_order"]):
        raise ValueError("prediction must include every fitted SR/CR channel exactly")
    if any(not row["present"] for row in source["signal"]) and any(
            sample["provenance"]["kind"] != "source_identity" for channel in channels.values() for sample in channel["samples"]):
        raise ValueError("incomplete published signal permits official identity witnesses only; new SR/CR predictions remain unknown")
    workspace = source_contract.workspace()
    poi = source["measurement"]["config"]["poi"]
    source_samples = {(channel["name"], sample["name"]): sample for channel in workspace["channels"]
                      for sample in channel["samples"] if sample["name"] in next(row["sample_names"] for row in source["signal"] if row["channel"] == channel["name"])}
    patch, reports, quantities = [], [], []
    for channel_index, channel in enumerate(workspace["channels"]):
        supplied_channel = channels[channel["name"]]
        supplied = supplied_channel["samples"]
        expected = {name for chan, name in source_samples if chan == channel["name"]}
        if not expected and not supplied:
            if supplied_channel.get("source_absent") is not True:
                raise ValueError("absent source signal must remain explicitly unknown")
            reports.append({"channel": channel["name"], "source_absent": True,
                            "interpretation": "no published signal addition; acceptance and new-model contribution unknown"})
            continue
        if supplied_channel.get("source_absent") is True:
            raise ValueError("a source signal contribution cannot be erased as absent")
        if {sample["name"] for sample in supplied} != expected:
            raise ValueError("prediction signal sample identities differ from the source channel")
        bins = len(next(item["data"] for item in workspace["observations"] if item["name"] == channel["name"]))
        for supplied_sample in supplied:
            if "prediction" in supplied_sample:
                from .event_inference_contract import prediction
                quantities.append({"channel": channel["name"], "sample": supplied_sample["name"],
                                   **prediction(supplied_sample["prediction"], base, supplied_sample, channel["name"])})
            sample = {key: deepcopy(supplied_sample[key]) for key in ("name", "data", "modifiers")}
            old = source_samples[channel["name"], sample["name"]]
            _vector(sample["data"], bins, "nominal signal yields")
            pairs = _modifiers(sample, bins, poi)
            old_pairs = {(m["name"], m["type"]) for m in old["modifiers"]}
            if pairs != old_pairs:
                raise ValueError("prediction changes source modifier identities or shared nuisance correlations")
            old_by_pair = {(m["name"], m["type"]): m for m in old["modifiers"]}
            # Reorder only to the original source order. Do not collapse equal
            # names across modifier types, because pyhf can share their parameter.
            by_pair = {(m["name"], m["type"]): m for m in sample["modifiers"]}
            sample["modifiers"] = [by_pair[m["name"], m["type"]] for m in old["modifiers"]]
            provenance, stat = supplied_sample["provenance"], supplied_sample["mc_stat"]
            for pin in provenance["evidence"]:
                published._bound_path(pin, base, published.MAX_MEMBER_BYTES)
            if provenance["kind"] == "source_identity" and sample != old:
                raise ValueError("source_identity prediction differs from the official sample")
            # Null-data modifiers define the POI/luminosity/free-factor structure.
            # Their identities were checked above and their data cannot be edited.
            statistics = [m for m in sample["modifiers"] if m["type"] in ("staterror", "shapesys")]
            if 'prediction' in supplied_sample:
                names = {modifier['name'] for modifier in statistics}
                occurrences = [modifier for row in workspace['channels'] for item in row['samples']
                               for modifier in item['modifiers'] if modifier['name'] in names]
                overrides = [parameter for parameter in source['measurement']['config']['parameters']
                             if parameter['name'] in names]
                if len(occurrences) != 1 or overrides:
                    validation_core.fail('template.prediction.covariance',
                        {'modifier_occurrences': len(occurrences), 'parameter_overrides': overrides},
                        'one unshared finite-MC modifier without parameter overrides',
                        repair='use a likelihood projection that retains the supplied signal covariance')
            if stat["mode"] == "source_preserved":
                if sample["data"] != old["data"] or any(m != old_by_pair[m["name"], m["type"]] for m in statistics):
                    raise ValueError("changed nominal or MC errors require supplied finite-MC treatment")
            else:
                _vector(stat["sumw"], bins, "MC sumw")
                _vector(stat["sumw2"], bins, "MC sumw2")
                if stat["sumw"] != sample["data"]:
                    raise ValueError("MC sumw differs from nominal signal yields")
                if len(statistics) != 1:
                    raise ValueError("supplied MC requires exactly one existing statistical modifier")
                errors = statistics[0]["data"]
                if any(not math.isclose(error * error, variance, rel_tol=1e-10, abs_tol=1e-14)
                       for error, variance in zip(errors, stat["sumw2"])):
                    raise ValueError("absolute MC errors differ from supplied sumw2")
                if any(yield_ == 0 and variance > 0 for yield_, variance in zip(stat["sumw"], stat["sumw2"])):
                    raise ValueError("zero/cancelling MC bin with positive variance cannot be represented")
                if any(yield_ > 0 and variance == 0 for yield_, variance in zip(stat["sumw"], stat["sumw2"])):
                    raise ValueError("positive finite-MC yield requires positive sumw2")
            if provenance["kind"] == "supplied_prediction":
                # When normalization and shape use one shared nuisance, the
                # absolute shape component must be normalized independently.
                # This prevents supplying a full rate variation twice. Official
                # identity templates retain their exact original decomposition.
                total = math.fsum(sample["data"])
                for name, kind in pairs:
                    if kind == "histosys" and (name, "normsys") in pairs:
                        shape = by_pair[name, "histosys"]["data"]
                        rate = by_pair[name, "normsys"]["data"]
                        if any(rate[anchor] != 1 and not math.isclose(math.fsum(shape[key]), total, rel_tol=1e-9, abs_tol=1e-12)
                               for key, anchor in (("hi_data", "hi"), ("lo_data", "lo"))):
                            raise ValueError("shared normalization/shape variation double-counts signal normalization")
            # shapesys drops a zero-nominal bin's parameter. staterror may instead
            # pool this sample with backgrounds, which is preserved and reported.
            for modifier in statistics:
                if modifier["type"] == "shapesys" and any(y == 0 and e > 0 for y, e in zip(sample["data"], modifier["data"])):
                    raise ValueError("positive shapesys error at zero nominal would be silently disabled")
            sample_index = next(i for i, old_sample in enumerate(channel["samples"]) if old_sample["name"] == sample["name"])
            channel["samples"][sample_index] = sample
            patch.append({"op": "replace", "path": f"/channels/{channel_index}/samples/{sample_index}", "value": sample})
            reports.append({"channel": channel["name"], "sample": sample["name"], "nominal": sample["data"],
                            "zero_bins": [i for i, value in enumerate(sample["data"]) if value == 0],
                            "modifier_name_types": [list(pair) for pair in sorted(pairs)],
                            "provenance": provenance, "mc_stat": stat})
    # staterror pools the absolute errors of all samples with the same name.
    # A zero signal nominal can be meaningful in such a pool; a zero *pool*
    # with positive uncertainty is disabled by pyhf and must be refused.
    for channel in workspace["channels"]:
        names = {m["name"] for sample in channel["samples"] for m in sample["modifiers"] if m["type"] == "staterror"}
        for name in names:
            affected = [(sample, m) for sample in channel["samples"] for m in sample["modifiers"]
                        if m["name"] == name and m["type"] == "staterror"]
            for bin_index in range(len(channel["samples"][0]["data"])):
                total = math.fsum(sample["data"][bin_index] for sample, _ in affected)
                error2 = math.fsum(m["data"][bin_index] ** 2 for _, m in affected)
                if total == 0 and error2 > 0:
                    raise ValueError("positive staterror at zero pooled nominal would be silently disabled")
    manifest = {"schema_version": 1, "scope": SCOPE, "template_id": template["template_id"],
                "quantity": {"weight_convention": "signed"},
                "template_compact_sha256": _digest(template), "workspace_compact_sha256": _digest(workspace),
                "source_workspace_compact_sha256": source["workspace_compact_sha256"], "source_contract": source,
                "measurement": source["measurement"], "modifier_settings": template["modifier_settings"],
                "channel_order": source["channel_order"], "signal": reports, "grounding": template["grounding"],
                "patch_compact_sha256": _digest(patch),
                "modifier_name_type_sharing": source["modifier_name_type_sharing"],
                "parameter_name_sharing": source["parameter_name_sharing"],
                "complete_signal_prediction": all(row["present"] for row in source["signal"]),
                "uncovered_channels": [row["channel"] for row in source["signal"] if not row["present"]],
                "mc_stat_interpretation": "source-preserved or supplied absolute finite-MC errors; shared staterror remains pooled with backgrounds; no raw-event covariance inferred",
                "identity_interpretation": "template identity is distinct even for an exact official identity workspace"}
    if quantities:
        from ravel.validation.core import fail
        # This projection has an exclusive-bin covariance, not cross-channel covariance.
        if len(quantities) != 1 or sum(len(c['samples']) for c in template['channels']) != 1:
            fail('template.prediction', len(quantities), 'one complete signal sample in one channel',
                 repair='supply the shared-event covariance to a compatible likelihood adapter')
        manifest['quantity_contracts'] = quantities
    return SignalTemplateContract(published._compact(manifest), published._compact(workspace), published._compact(patch))


def identity_template(source_contract, template_id):
    """Create an exact source-control document, never a new-model prediction."""
    source = source_contract.manifest()
    workspace = source_contract.workspace()
    by_channel = {row["channel"]: set(row["sample_names"]) for row in source["signal"]}
    channels = [{"name": channel["name"], "samples": [dict(deepcopy(sample),
                  provenance={"kind": "source_identity", "description": "Exact released signal point; identity control only",
                              "evidence": [], "normalization_shape": "source_decomposition"},
                  mc_stat={"mode": "source_preserved", "description": "Exact released finite-MC modifier and sharing"})
                 for sample in channel["samples"] if sample["name"] in by_channel[channel["name"]]]}
                for channel in workspace["channels"]]
    for channel in channels:
        if not channel["samples"]:
            channel["source_absent"] = True
    return validate_template({"schema_version": 1, "template_id": template_id,
                              "source_workspace_sha256": source["workspace_compact_sha256"],
                              "modifier_settings": deepcopy(MODIFIER_SETTINGS), "channels": channels, "grounding": []})


def compile_signal_template(contract):
    """Compile the preserved HistFactory family for existing general inference."""
    import pyhf
    manifest = contract.manifest()
    if manifest["modifier_settings"] != MODIFIER_SETTINGS:
        raise ValueError("compiled template changes the admitted source interpolation settings")
    if _digest(contract.workspace()) != manifest["workspace_compact_sha256"]:
        raise ValueError("template workspace identity differs from manifest")
    workspace = pyhf.Workspace(contract.workspace())
    model = workspace.model(measurement_name=manifest["measurement"]["name"],
                            modifier_settings=manifest["modifier_settings"])
    data = [float(value) for value in workspace.data(model)]
    constraints = {}
    for name in model.config.par_order:
        pset = model.config.param_set(name)
        constraints[name] = {key: getattr(pset, key) for key in ("n_parameters", "constrained", "auxdata", "sigmas", "factors", "pdf_type") if hasattr(pset, key)}
    compiled = {"schema_version": 1, "pyhf_version": pyhf.__version__, "measurement": manifest["measurement"],
                "modifier_settings": manifest["modifier_settings"], "template_compact_sha256": manifest["template_compact_sha256"],
                "workspace_compact_sha256": manifest["workspace_compact_sha256"], "parameter_order": model.config.par_order,
                "parameter_names": model.config.par_names, "channel_order": model.config.channels,
                "channel_slices": {name: [part.start, part.stop] for name, part in model.config.channel_slices.items()},
                "sample_order": model.config.samples, "nmaindata": model.config.nmaindata,
                "npars": model.config.npars, "nauxdata": model.config.nauxdata,
                "inits": model.config.suggested_init(), "bounds": model.config.suggested_bounds(),
                "fixed": model.config.suggested_fixed(), "constraints": constraints, "auxdata": model.config.auxdata,
                "observed_and_auxiliary_data": data, "model_compact_sha256": _digest(model.spec),
                "data_compact_sha256": _digest(data), "scope": "compiled supplied-template model; no numerical or detector certification"}
    return model, data, compiled


def load_signal_template(document, base="."):
    document = validate_document(document)
    source_path, source_raw = published._bound_path(document["published_model"], base, published.MAX_INPUT_BYTES)
    template_path, template_raw = published._bound_path(document["template"], base, MAX_TEMPLATE_BYTES)
    source = published.load_published_model(published._json(source_raw), source_path.parent)
    contract = build_signal_template(source, published._json(template_raw), template_path.parent)
    manifest = contract.manifest()
    manifest["input_bindings"] = deepcopy(document)
    return SignalTemplateContract(published._compact(manifest), contract.workspace_json, contract.patch_json)


def _load(task, base):
    from ravel.workflow.science import regular
    path = regular(validate(task)["input"], base)
    if path.stat().st_size > published.MAX_INPUT_BYTES:
        raise ValueError("signal-template bridge exceeds byte admission")
    raw = path.read_bytes()
    if len(raw) > published.MAX_INPUT_BYTES:
        raise ValueError("signal-template bridge exceeds byte admission")
    return path, validate_document(published._json(raw)), raw


def inputs(task, base):
    """Enumerate all transitive byte-bound inputs without compiling or fitting."""
    path, document, _ = _load(task, base)
    source_path, source_raw = published._bound_path(document["published_model"], path.parent, published.MAX_INPUT_BYTES)
    template_path, template_raw = published._bound_path(document["template"], path.parent, MAX_TEMPLATE_BYTES)
    template = validate_template(published._json(template_raw))
    pins = list(template["grounding"])
    pins.extend(pin for channel in template["channels"] for sample in channel["samples"] for pin in sample["provenance"]["evidence"])
    prediction_files = []
    for channel in template['channels']:
        for sample in channel['samples']:
            if 'prediction' in sample:
                from .event_inference_contract import prediction, prediction_inputs
                prediction(sample['prediction'], template_path.parent, sample, channel['name'])
                prediction_files += prediction_inputs(sample['prediction'], template_path.parent)
    # Validate source document bytes before asking its input enumerator to read it.
    published.validate_document(published._json(source_raw))
    return [path, source_path, template_path, *published.inputs({"input": str(source_path)}, source_path.parent),
            *[published._bound_path(pin, template_path.parent, published.MAX_MEMBER_BYTES)[0] for pin in pins],
            *prediction_files]


def run(task, base, out):
    """Approved numerical adapter. The scientific worker owns wall supervision."""
    from ravel.workflow.state_io import atomic_json
    operation = validate(task).get("operation", "inference")
    path, document, raw = _load(task, base)
    inputs(task, base)
    contract = load_signal_template(document, path.parent)
    if operation == "inference" and not contract.manifest()["complete_signal_prediction"]:
        raise ValueError("new-signal inference requires complete SR/CR predictions; source omissions remain unknown")
    source_path, source_raw = published._bound_path(document["published_model"], path.parent, published.MAX_INPUT_BYTES)
    protocol = published.validate_document(published._json(source_raw))["inference"]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("signal-template output must be empty; earlier attempts are immutable")
    atomic_json(out / "signal_template_contract.json", contract.manifest())
    atomic_json(out / "signal_template_workspace.json", contract.workspace())
    atomic_json(out / "signal_template_patch.json", contract.patch())
    import pyhf
    if operation == "compile":
        pyhf.set_backend(protocol["backend"], precision="64b")
        _, _, compiled = compile_signal_template(contract)
        atomic_json(out / "signal_template_compiled.json", compiled)
        return {"status": "passed", "operation": "compile", "physics_validated": False,
                "scope": "source-bound template compilation only; no numerical inference or detector certification",
                "numerical_inference": False, "generated_events": 0,
                "complete_signal_prediction": contract.manifest()["complete_signal_prediction"],
                "contract": "signal_template_contract.json", "compiled": "signal_template_compiled.json",
                "workspace": "signal_template_workspace.json", "patch": "signal_template_patch.json", "inference": None}
    from ravel.physics import pyhf_exclude as engine
    pyhf.set_backend(protocol["backend"], engine.robust_optimizer(maxiter=200000, tolerance=protocol["fit_tolerance"]), precision="64b")
    model, data, compiled = compile_signal_template(contract)
    atomic_json(out / "signal_template_compiled.json", compiled)
    diagnostic, witnesses = {}, {}
    try:
        result = engine.compute(model, data, n_curve=protocol["n_curve"], poi_cap=protocol["poi_cap"],
                                root_rtol=protocol["root_rtol"], diagnostic_record=diagnostic,
                                profile_witness_record=witnesses, profile_witness_limits=protocol["witness_limits"],
                                profile_witness_context={"contract": contract.manifest(), "input_sha256": hashlib.sha256(raw).hexdigest()},
                                profile_witness_journal=out / "profile_witnesses.jsonl")
        if [result["limit_status"]["observed"], *result["limit_status"]["expected"]] != ["resolved"] * 6:
            raise RuntimeError("signal-template inference requires all six resolved roots")
        atomic_json(out / "exclusion.json", result)
        if contract.manifest().get('quantity_contracts'):
            from .event_inference_contract import inference_output
            atomic_json(out / 'inference-quantity-contract.json', inference_output(contract, compiled, result))
        status, error = "passed", None
    except Exception as exc:
        status, error = "failed", {"type": type(exc).__name__, "message": str(exc)}
        atomic_json(out / "inference_failure.json", {"status": status, "error": error, "diagnostics": diagnostic})
    finally:
        atomic_json(out / "profile_witnesses.json", witnesses)
        atomic_json(out / "inference_diagnostics.json", diagnostic)
    delivery = {"status": status, "operation": "inference", "numerical_inference": True,
            "physics_validated": False, "scope": SCOPE, "generated_events": 0,
            "contract": "signal_template_contract.json", "compiled": "signal_template_compiled.json",
            "inference": "exclusion.json" if status == "passed" else None, "error": error,
            "profile_witnesses": "profile_witnesses.json", "profile_witness_journal": "profile_witnesses.jsonl"}
    if status == 'passed' and contract.manifest().get('quantity_contracts'):
        from .event_inference_contract import file_pin
        delivery['quantity_artifact'] = file_pin(out / 'inference-quantity-contract.json')
    return delivery
