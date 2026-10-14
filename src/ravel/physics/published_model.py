"""Exact, source-bound published HistFactory patch oracle.

This imports an untouched released workspace and one exact typed coordinate.
Nominal coefficients, source presence, shared modifiers and compiled constraints
remain separate from numerical inference and from detector/coverage validation.
Archive hashes establish byte custody; attribution is the supplied source record.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
SCOPE = "source-bound published likelihood inversion; no detector or coverage certification"


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def canonical_background_digest(value):
    """pyhf PatchSet SHA256 uses sorted JSON with its default separators."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    # Overflow in a valid numeric token, e.g. 1e999, bypasses parse_constant.
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("nonfinite JSON number")
        if isinstance(item, dict):
            for child in item.values():
                finite(child)
        elif isinstance(item, list):
            for child in item:
                finite(child)
    finite(value)
    return value


def _keys(value, required, optional=(), *, label):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError(label + " requires exactly " + ", ".join(required) + (" plus optional " + ", ".join(optional) if optional else ""))


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be a nonempty string")
    return value


def _sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(label + " must be a lowercase SHA256")
    return value


def _coordinate(value):
    # Coordinates use the documented finite binary JSON-number semantics:
    # 225 and 225.0 are equal, and decimal-token precision is not retained.
    # Strings and booleans do not substitute, nor is interpolation admitted.
    if isinstance(value, str):
        return ("string", _text(value, "coordinate"))
    if type(value) in (int, float) and math.isfinite(value):
        return ("number", value)
    raise ValueError("coordinates must be finite JSON numbers or nonempty strings")


def _bound_path(pin, base, limit):
    from ravel.workflow.science import regular
    _keys(pin, ("path", "sha256"), label="file binding")
    path = regular(_text(pin["path"], "source path"), base)
    expected = _sha(pin["sha256"], "source digest")
    if path.stat().st_size > limit:
        raise ValueError("source exceeds byte admission: " + str(path))
    raw = path.read_bytes()
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("source bytes differ from binding: " + str(path))
    return path, raw


def validate(task):
    """Supervised adapter task; paths inside its JSON are relative to that file."""
    _keys(task, ("input",), label="published-model task")
    _text(task["input"], "published-model input path")
    return deepcopy(task)


# The environment name is retained for clients migrating declarations; it grants no authority.
REFERENCE_ACKS_ENV = "RAVEL_PUBLISHED_REFERENCE_ACKS"


def _validate_reference_acknowledgment(document, base="."):
    from . import reviewed_source as records
    ack = document["source_reference_acknowledgment"]
    if not isinstance(ack, dict) or "reviewed_registry" not in ack:
        raise records.SourceRecordError("missing_reviewed_erratum", "explicit byte-bound reviewed errata registry required")
    _keys(ack, ("kind", "field", "observed", "external_record", "reviewed_registry"), label="source reference acknowledgment")
    value, sources, inputs, capture = records.load(ack["reviewed_registry"], base, "errata-registry", "missing_reviewed_erratum")
    matches = [row for row in value["errata"] if row["id"] == ack["kind"]]
    if len(matches) != 1:
        raise records.SourceRecordError("missing_reviewed_erratum", "one matching reviewed erratum required")
    entry = matches[0]
    if (entry["field"] != ack["field"] or not ack["field"].startswith("/metadata/")
            or records.encoded(entry["observed"]) != records.encoded(ack["observed"])
            or entry["source"] != document["source"] or entry["archive_sha256"] != document["archive"]["sha256"]
            or entry["members"] != document["members"]):
        raise records.SourceRecordError("source_scope_mismatch", "reviewed erratum source, members or affected field differs")
    label = entry["external_record_source"]
    if label not in sources:
        raise records.SourceRecordError("invalid_source_record", "erratum external record source absent")
    external_path, external_raw = capture.pin(ack["external_record"], base)
    if external_raw != sources[label]:
        raise records.SourceRecordError("source_scope_mismatch", "external record differs from reviewed bytes")
    external = records.document(external_raw)
    if not entry["external_assertions"]:
        raise records.SourceRecordError("invalid_source_record", "external attribution assertions required")
    for assertion in entry["external_assertions"]:
        if records.encoded(records.select(external, assertion["pointer"])) != records.encoded(assertion["expected"]):
            raise records.SourceRecordError("source_scope_mismatch", "external attribution assertion differs")
    capture.finish()
    return ack, entry, inputs, value["review"]


def _verified_reference_acknowledgment(document, metadata, base):
    from . import reviewed_source as records
    ack, entry, inputs, review = _validate_reference_acknowledgment(document, base)
    if records.encoded(records.select({"metadata": metadata}, ack["field"])) != records.encoded(ack["observed"]):
        raise records.SourceRecordError("source_scope_mismatch", "acknowledgment differs from literal source metadata")
    return {"kind": ack["kind"], "field": ack["field"], "literal_source_value": deepcopy(ack["observed"]),
            "external_record_id": document["source"]["record_id"],
            "reviewed_inputs": inputs, "review": deepcopy(review), "source_bytes_modified": False,
            "scope": "Exact metadata discrepancy only; no model, inference or physics qualification"}


def validate_document(document, base="."):
    _keys(document, ("schema_version", "source", "archive", "members", "coordinates",
                     "measurement", "expected_background_digest", "inference", "grounding"),
          optional=("source_reference_acknowledgment",), label="published-model input")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported published-model schema_version")
    _keys(document["source"], ("record_id", "version", "resource_id", "record_url", "archive_url", "doi"), label="published source")
    for key, value in document["source"].items():
        if key == "version":
            if type(value) is not int or value < 1:
                raise ValueError("source version must be a positive integer")
        else:
            _text(value, "source " + key)
    _keys(document["archive"], ("path", "sha256"), label="archive binding")
    _text(document["archive"]["path"], "archive path")
    _sha(document["archive"]["sha256"], "archive digest")
    _keys(document["members"], ("background", "patchset"), label="archive members")
    for member in document["members"].values():
        _keys(member, ("name", "sha256"), label="member binding")
        name = _text(member["name"], "member name")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("member name must be an exact safe relative archive path")
        _sha(member["sha256"], "member digest")
    if document["members"]["background"]["name"] == document["members"]["patchset"]["name"]:
        raise ValueError("background and patchset members must be distinct")
    coordinates = document["coordinates"]
    if not isinstance(coordinates, dict) or not coordinates:
        raise ValueError("exact labelled coordinates are required")
    for key, value in coordinates.items():
        _text(key, "coordinate label")
        _coordinate(value)
    _text(document["measurement"], "measurement name")
    _sha(document["expected_background_digest"], "canonical background digest")
    if not isinstance(document["grounding"], list):
        raise ValueError("grounding must be a list of byte-bound source evidence")
    for pin in document["grounding"]:
        _keys(pin, ("path", "sha256"), label="grounding binding")
        _text(pin["path"], "grounding path")
        _sha(pin["sha256"], "grounding digest")
    if "source_reference_acknowledgment" in document:
        _validate_reference_acknowledgment(document, base)
    inference = document["inference"]
    _keys(inference, ("backend", "fit_tolerance", "poi_cap", "root_rtol", "n_curve",
                     "poi_domain_policy", "retain_profile_witnesses", "witness_limits"), label="inference protocol")
    if inference["poi_domain_policy"] != "engine_dynamic_nonnegative":
        raise ValueError("only the explicitly declared existing engine POI-domain rule is implemented")
    if inference["backend"] not in ("numpy", "jax"):
        raise ValueError("unsupported explicit tensor backend")
    for key in ("fit_tolerance", "poi_cap", "root_rtol"):
        value = inference[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(key + " must be positive and finite")
    if inference["fit_tolerance"] >= 1 or not 4 * 2.220446049250313e-16 <= inference["root_rtol"] < 1:
        raise ValueError("fit/root tolerances outside admissible range")
    if type(inference["n_curve"]) is not int or not 2 <= inference["n_curve"] <= 101:
        raise ValueError("n_curve must be an integer from 2 to 101")
    if inference["retain_profile_witnesses"] is not True:
        raise ValueError("published-model inference requires retained profile witnesses")
    limits = inference["witness_limits"]
    _keys(limits, ("evaluations", "minimizations", "bytes"), label="witness limits")
    for key, maximum in (("evaluations", 5000), ("minimizations", 50000), ("bytes", 512 * 1024 * 1024)):
        minimum = 512 if key == "bytes" else 1
        if type(limits[key]) is not int or not minimum <= limits[key] <= maximum:
            raise ValueError("witness " + key + " outside admitted bound")
    return deepcopy(document)


def _load_bytes(task, base):
    from ravel.workflow.science import regular
    path = regular(validate(task)["input"], base)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("published-model input exceeds byte limit")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("published-model input exceeds byte limit")
    return path, validate_document(_json(raw), path.parent), raw


def _load(task, base):
    path, document, _ = _load_bytes(task, base)
    return path, document


def inputs(task, base):
    """Read and bind small source inventory; no schema compilation or inference."""
    path, document = _load(task, base)
    archive, _ = _bound_path(document["archive"], path.parent, MAX_ARCHIVE_BYTES)
    acknowledgment_inputs = []
    if "source_reference_acknowledgment" in document:
        _, _, bindings, _ = _validate_reference_acknowledgment(document, path.parent)
        acknowledgment_inputs = [Path(pin["path"]) for pin in bindings]
    return [path, archive, *[_bound_path(pin, path.parent, MAX_MEMBER_BYTES)[0] for pin in document["grounding"]], *acknowledgment_inputs]



@dataclass(frozen=True)
class PublishedModelContract:
    """Immutable JSON byte representations prevent post-admission model mutation."""
    manifest_json: bytes
    background_json: bytes
    patchset_json: bytes
    patch_json: bytes
    workspace_json: bytes

    def manifest(self):
        return _json(self.manifest_json)

    def workspace(self):
        return _json(self.workspace_json)

    def patch(self):
        return _json(self.patch_json)


def load_published_model(document, base="."):
    """Verify exact archive/member/digest/coordinate and preserve add semantics.

    No likelihood is evaluated. This importer admits signal-sample additions
    only; replacing observations/backgrounds requires a different contract.
    Omitted additions are marked absent, not a zero-acceptance measurement.
    """
    document = validate_document(document, base)
    archive_path, archive_raw = _bound_path(document["archive"], base, MAX_ARCHIVE_BYTES)
    raw, member_pins = {}, {}
    # Consume the admitted byte snapshot, never reopen a mutable path.
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:*") as archive:
        archive_members, declared_bytes = [], 0
        for member in archive:
            declared_bytes += member.size
            if len(archive_members) >= MAX_ARCHIVE_MEMBERS or declared_bytes > MAX_ARCHIVE_EXPANDED_BYTES:
                raise ValueError("archive member count or declared expanded bytes exceeds admission")
            archive_members.append(member)
        for role, binding in document["members"].items():
            matches = [member for member in archive_members if member.name == binding["name"]]
            if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size <= MAX_MEMBER_BYTES:
                raise ValueError("archive member missing, duplicated, nonregular or oversized: " + binding["name"])
            stream = archive.extractfile(matches[0])
            raw[role] = stream.read(MAX_MEMBER_BYTES + 1)
            digest = hashlib.sha256(raw[role]).hexdigest()
            if len(raw[role]) != matches[0].size or digest != binding["sha256"]:
                raise ValueError("archive member bytes differ: " + binding["name"])
            member_pins[role] = {**binding, "bytes": len(raw[role])}
    background, patchset = _json(raw["background"]), _json(raw["patchset"])
    metadata = patchset.get("metadata", {})
    reference_acknowledgment = None
    if "source_reference_acknowledgment" in document:
        reference_acknowledgment = _verified_reference_acknowledgment(document, metadata, base)
    if ("hepdata" in metadata.get("references", {})
            and metadata["references"]["hepdata"] != document["source"]["record_id"]
            and (reference_acknowledgment is None
                 or reference_acknowledgment["field"] != "/metadata/references/hepdata"
                 or reference_acknowledgment["literal_source_value"] != metadata["references"]["hepdata"])):
        from .reviewed_source import SourceRecordError
        raise SourceRecordError("missing_reviewed_erratum", "source record differs from patchset HEPData reference; supplied reviewed erratum required")
    digest = canonical_background_digest(background)
    if metadata.get("digests", {}).get("sha256") != digest or document["expected_background_digest"] != digest:
        raise ValueError("patchset-declared canonical background identity mismatch")
    labels = metadata.get("labels")
    if not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("patchset coordinate labels must be distinct nonempty strings")
    if set(document["coordinates"]) != set(labels):
        raise ValueError("requested coordinate labels differ from released patchset")
    requested = tuple(_coordinate(document["coordinates"][label]) for label in labels)
    catalogue, selected = set(), None
    patches = patchset.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("patchset must contain patches")
    for index, patch in enumerate(patches):
        values = patch.get("metadata", {}).get("values")
        if not isinstance(values, list) or len(values) != len(labels):
            raise ValueError("patch coordinates do not match labels")
        key = tuple(_coordinate(value) for value in values)
        if key in catalogue:
            raise ValueError("duplicate exact typed patch coordinates")
        catalogue.add(key)
        if key == requested:
            selected = index, patch
    if selected is None:
        raise ValueError("requested exact coordinate is absent; interpolation is not admitted")
    index, patch = selected
    measurements = background.get("measurements", [])
    names = [item.get("name") for item in measurements]
    if len(set(names)) != len(names) or names.count(document["measurement"]) != 1:
        raise ValueError("requested measurement is missing or ambiguous")
    measurement = deepcopy(measurements[names.index(document["measurement"])])
    poi = _text(measurement.get("config", {}).get("poi"), "measurement POI")
    channels = background.get("channels", [])
    channel_names = [item.get("name") for item in channels]
    if not channels or any(not isinstance(name, str) or not name for name in channel_names) or len(set(channel_names)) != len(channel_names):
        raise ValueError("background channel names must be distinct")
    observations = {item["name"]: item["data"] for item in background.get("observations", [])}
    if len(observations) != len(background.get("observations", [])) or set(observations) != set(channel_names):
        raise ValueError("observations do not uniquely match all background channels")
    workspace = deepcopy(background)
    if any(modifier.get("name") == poi for channel in channels for sample in channel["samples"] for modifier in sample.get("modifiers", [])):
        raise ValueError("background samples must be independent of the signal POI")
    added = [[] for _ in channels]
    operations = patch.get("patch")
    if not isinstance(operations, list) or not operations:
        raise ValueError("selected patch must add signal samples")
    for operation in operations:
        _keys(operation, ("op", "path", "value"), label="signal patch operation")
        match = re.fullmatch(r"/channels/(0|[1-9][0-9]*)/samples/(0|[1-9][0-9]*|-)", operation["path"])
        if operation["op"] != "add" or match is None:
            raise ValueError("only exact signal-sample add operations are admitted")
        channel_index = int(match[1])
        if channel_index >= len(channels):
            raise ValueError("signal addition channel index outside workspace")
        samples = workspace["channels"][channel_index]["samples"]
        sample_index = len(samples) if match[2] == "-" else int(match[2])
        if sample_index > len(samples):
            raise ValueError("signal insertion index outside current sample array")
        sample = deepcopy(operation["value"])
        _keys(sample, ("name", "data", "modifiers"), label="signal sample")
        _text(sample["name"], "signal sample name")
        if sample["name"] in [existing["name"] for existing in samples]:
            raise ValueError("signal addition duplicates an existing sample name")
        counts = sample["data"]
        if not isinstance(counts, list) or len(counts) != len(observations[channel_names[channel_index]]) or not counts:
            raise ValueError("signal coefficients do not match channel bin count")
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in counts):
            raise ValueError("signal coefficients must be finite nonnegative numbers")
        if not isinstance(sample["modifiers"], list) or sum(modifier.get("name") == poi and modifier.get("type") == "normfactor" for modifier in sample["modifiers"]) != 1:
            raise ValueError("each signal addition must contain exactly one measurement POI normfactor")
        samples.insert(sample_index, sample)
        added[channel_index].append(sample)
    graph = {}
    name_instances = {}
    for origin, channel_list in (("background", background["channels"]), ("signal", [dict(name=name, samples=samples) for name, samples in zip(channel_names, added)])):
        for channel in channel_list:
            for sample in channel["samples"]:
                seen = set()
                for modifier in sample["modifiers"]:
                    _keys(modifier, ("name", "type", "data"), label="modifier")
                    key = (_text(modifier["name"], "modifier name"), _text(modifier["type"], "modifier type"))
                    if key in seen:
                        raise ValueError("duplicate modifier name/type in one sample")
                    seen.add(key)
                    by_name = name_instances.setdefault(key[0], {"name": key[0], "types": set(), "background": [], "signal": []})
                    by_name["types"].add(key[1])
                    by_name[origin].append({"channel": channel["name"], "sample": sample["name"], "type": key[1]})
                    entry = graph.setdefault(key, {"name": key[0], "type": key[1], "background": [], "signal": []})
                    entry[origin].append({"channel": channel["name"], "sample": sample["name"]})
    signal = [{"channel": name, "present": bool(samples), "sample_names": [sample["name"] for sample in samples],
               "nominal": [math.fsum(sample["data"][i] for sample in samples) for i in range(len(observations[name]))]}
              for name, samples in zip(channel_names, added)]
    manifest = {"schema_version": 1, "scope": "source-bound nominal/constraint contract; no inference or acceptance certification",
                "source": document["source"], "archive": {"path": str(archive_path), "sha256": hashlib.sha256(archive_raw).hexdigest(), "bytes": len(archive_raw)},
                "members": member_pins, "canonical_background_sha256": digest,
                "coordinate_labels": labels, "coordinates": document["coordinates"], "patch_index": index,
                "patch_metadata": patch["metadata"], "patch_compact_sha256": hashlib.sha256(_compact(operations)).hexdigest(),
                "measurement": measurement, "channel_order": channel_names, "signal": signal,
                "modifier_name_type_sharing": [dict(entry, shared_with_background=bool(entry["background"] and entry["signal"])) for _, entry in sorted(graph.items())],
                "parameter_name_sharing": [dict(entry, types=sorted(entry["types"]), shared_with_background=bool(entry["background"] and entry["signal"])) for _, entry in sorted(name_instances.items())],
                "workspace_compact_sha256": hashlib.sha256(_compact(workspace)).hexdigest(),
                "absence_interpretation": "no source signal addition; zero supplied-model coefficient does not certify zero acceptance or precision",
                "signal_sampling_covariance": None,
                "covariance_interpretation": "shared staterror constraints are not raw signal-event covariance"}
    if reference_acknowledgment is not None:
        manifest["source_reference_acknowledgment"] = reference_acknowledgment
    return PublishedModelContract(_compact(manifest), raw["background"], raw["patchset"], _compact(operations), _compact(workspace))


def compile_published_model(contract):
    """Use pyhf's verified PatchSet application and the existing engine settings."""
    import pyhf
    from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
    manifest = contract.manifest()
    patchset = pyhf.PatchSet(_json(contract.patchset_json))
    workspace = patchset.apply(_json(contract.background_json),
                               tuple(manifest["coordinates"][label] for label in manifest["coordinate_labels"]))
    if _compact(workspace) != contract.workspace_json:
        raise ValueError("independent signal-add projection differs from pyhf PatchSet semantics")
    model = workspace.model(measurement_name=manifest["measurement"]["name"], modifier_settings=MODIFIER_SETTINGS)
    workspace_data = workspace.data(model)
    # The inference engine admits float data. Retain the workspace representation
    # separately so integer/float JSON spelling cannot create a false mismatch.
    data = [float(value) for value in workspace_data]
    constraints = {}
    for name in model.config.par_order:
        pset = model.config.param_set(name)
        constraints[name] = {key: getattr(pset, key) for key in ("n_parameters", "constrained", "auxdata", "sigmas", "factors", "pdf_type") if hasattr(pset, key)}
    compiled = {"schema_version": 1, "pyhf_version": pyhf.__version__, "modifier_settings": MODIFIER_SETTINGS,
                "measurement": manifest["measurement"], "parameter_order": model.config.par_order,
                "channel_order": model.config.channels,
                "channel_slices": {name: [part.start, part.stop] for name, part in model.config.channel_slices.items()},
                "sample_order": model.config.samples, "nmaindata": model.config.nmaindata,
                "parameter_names": model.config.par_names, "bounds": model.config.suggested_bounds(),
                "inits": model.config.suggested_init(), "fixed": model.config.suggested_fixed(),
                "npars": model.config.npars, "nauxdata": model.config.nauxdata, "auxdata": model.config.auxdata,
                "constraints": constraints, "observed_and_auxiliary_data": data,
                "model_compact_sha256": hashlib.sha256(_compact(model.spec)).hexdigest(),
                "data_compact_sha256": hashlib.sha256(json.dumps(data, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                "workspace_data_compact_sha256": hashlib.sha256(json.dumps(workspace_data, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                "data_representation": "float-normalized inference data; original workspace JSON representation separately pinned",
                "scope": "compiled supplied-model semantics only; no likelihood or optimizer evaluated"}
    return model, data, compiled


def run(task, base, out):
    """Approved single-model numerical adapter; caller owns total wall supervision."""
    from ravel.workflow.state_io import atomic_json
    path, document, input_raw = _load_bytes(task, base)
    # Rebind every grounding artifact immediately before construction.
    for pin in document["grounding"]:
        _bound_path(pin, path.parent, MAX_MEMBER_BYTES)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("published-model output must be empty; inference never overwrites an earlier attempt")
    contract = load_published_model(document, path.parent)
    atomic_json(out / "published_model_contract.json", contract.manifest())
    atomic_json(out / "published_workspace.json", contract.workspace())
    atomic_json(out / "published_signal_patch.json", contract.patch())
    import pyhf
    from ravel.physics import pyhf_exclude as engine
    protocol = document["inference"]
    pyhf.set_backend(protocol["backend"], engine.robust_optimizer(maxiter=200000, tolerance=protocol["fit_tolerance"]), precision="64b")
    model, data, compiled = compile_published_model(contract)
    atomic_json(out / "published_model_compiled.json", compiled)
    diagnostic, witnesses = {}, {}
    try:
        result = engine.compute(model, data, n_curve=protocol["n_curve"], poi_cap=protocol["poi_cap"],
                                root_rtol=protocol["root_rtol"], diagnostic_record=diagnostic,
                                profile_witness_record=witnesses,
                                profile_witness_limits=protocol["witness_limits"],
                                profile_witness_context={"contract": contract.manifest(), "input_sha256": hashlib.sha256(input_raw).hexdigest()},
                                profile_witness_journal=out / "profile_witnesses.jsonl")
        statuses = [result["limit_status"]["observed"], *result["limit_status"]["expected"]]
        if statuses != ["resolved"] * 6:
            raise RuntimeError("official oracle requires all six resolved roots")
        atomic_json(out / "exclusion.json", result)
        status, error = "passed", None
    except Exception as exc:
        status, error = "failed", {"type": type(exc).__name__, "message": str(exc)}
        atomic_json(out / "inference_failure.json", {"status": status, "error": error, "diagnostics": diagnostic})
    finally:
        atomic_json(out / "profile_witnesses.json", witnesses)
        atomic_json(out / "inference_diagnostics.json", diagnostic)
    return {"status": status, "physics_validated": False, "scope": SCOPE, "generated_events": 0,
            "contract": "published_model_contract.json", "compiled": "published_model_compiled.json",
            "inference": "exclusion.json" if status == "passed" else None, "error": error,
            "profile_witnesses": "profile_witnesses.json", "profile_witness_journal": "profile_witnesses.jsonl"}
