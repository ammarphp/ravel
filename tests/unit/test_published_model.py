"""Exact-source oracle contracts; compilation checks do not run an optimizer."""
from copy import deepcopy
import hashlib
import gzip
import io
import json
import tarfile

import pytest

from ravel.physics import published_model as oracle


def fixture(tmp_path, *, change=None):
    background = {"version": "1.0.0", "channels": [
        {"name": "SR", "samples": [{"name": "background", "data": [10.0],
                                    "modifiers": [{"name": "shared", "type": "staterror", "data": [2.0]}]}]},
        {"name": "CR", "samples": [{"name": "background", "data": [20.0], "modifiers": []}]},
    ], "observations": [{"name": "SR", "data": [12]}, {"name": "CR", "data": [20]}],
        "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}]}
    signal = {"name": "signal", "data": [4.0], "modifiers": [
        {"name": "mu", "type": "normfactor", "data": None},
        {"name": "shared", "type": "staterror", "data": [1.0]},
    ]}
    patchset = {"version": "1.0.0", "metadata": {
        "analysis_id": "test", "description": "synthetic source-contract control",
        "labels": ["chirality", "mass"], "references": {"hepdata": "ins0001001"},
        "digests": {"sha256": oracle.canonical_background_digest(background)}},
        "patches": [{"metadata": {"name": "point", "values": ["degenerate", 225.0]},
                     "patch": [{"op": "add", "path": "/channels/0/samples/0", "value": signal}]}]}
    if change:
        change(background, patchset)
        patchset["metadata"]["digests"]["sha256"] = oracle.canonical_background_digest(background)
    raw = {"background": json.dumps(background).encode(), "patchset": json.dumps(patchset).encode()}
    archive = tmp_path / "model.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for role, data in raw.items():
            member = tarfile.TarInfo("release/" + role + ".json")
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    document = {"schema_version": 1,
        "source": {"record_id": "ins0001001", "version": 1, "resource_id": "fixture",
                   "record_url": "https://example.invalid/record", "archive_url": "https://example.invalid/model", "doi": "synthetic fixture"},
        "archive": {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
        "members": {role: {"name": "release/" + role + ".json", "sha256": hashlib.sha256(data).hexdigest()} for role, data in raw.items()},
        "coordinates": {"mass": 225, "chirality": "degenerate"}, "measurement": "M",
        "expected_background_digest": oracle.canonical_background_digest(background), "grounding": [],
        "inference": {"backend": "numpy", "fit_tolerance": 1e-7, "poi_cap": 128.0,
                      "root_rtol": 1e-4, "n_curve": 11, "poi_domain_policy": "engine_dynamic_nonnegative", "retain_profile_witnesses": True,
                      "witness_limits": {"evaluations": 5000, "minimizations": 50000, "bytes": 268435456}}}
    return document, background, patchset


def test_exact_identity_presence_insertion_and_shared_graph(tmp_path):
    document, background, _ = fixture(tmp_path)
    contract = oracle.load_published_model(document)
    manifest = contract.manifest()
    assert manifest["channel_order"] == ["SR", "CR"]
    assert manifest["signal"] == [
        {"channel": "SR", "present": True, "sample_names": ["signal"], "nominal": [4]},
        {"channel": "CR", "present": False, "sample_names": [], "nominal": [0]},
    ]
    assert contract.workspace()["channels"][0]["samples"][0]["name"] == "signal"
    shared = next(row for row in manifest["modifier_name_type_sharing"] if row["name"] == "shared")
    assert shared["shared_with_background"]
    assert shared["signal"] == [{"channel": "SR", "sample": "signal"}]
    assert manifest["signal_sampling_covariance"] is None
    assert manifest["canonical_background_sha256"] == oracle.canonical_background_digest(background)
    # Public projections are copies; mutating one cannot change admitted bytes.
    manifest["signal"][0]["nominal"][0] = 100
    assert contract.manifest()["signal"][0]["nominal"] == [4]


def test_verified_pyhf_application_preserves_joint_staterror(tmp_path):
    pytest.importorskip("pyhf")
    document, _, _ = fixture(tmp_path)
    model, data, compiled = oracle.compile_published_model(oracle.load_published_model(document))
    assert compiled["constraints"]["shared"]["sigmas"] == pytest.approx([5 ** 0.5 / 14])
    assert data[:model.config.nmaindata] == [20, 12]  # pyhf's channel order is explicit in model.
    assert compiled["modifier_settings"] == {"normsys": {"interpcode": "code4"}, "histosys": {"interpcode": "code4p"}}
    assert compiled["measurement"]["name"] == "M"


def test_compiled_data_identity_matches_float_inference_representation(tmp_path):
    pytest.importorskip("pyhf")
    document, _, _ = fixture(tmp_path)
    model, data, compiled = oracle.compile_published_model(oracle.load_published_model(document))
    assert all(isinstance(value, float) for value in data)
    assert compiled["observed_and_auxiliary_data"] == data
    raw_data = [20, 12, *model.config.auxdata]
    digest = lambda values: hashlib.sha256(json.dumps(values, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert compiled["data_compact_sha256"] == digest([float(value) for value in raw_data])
    assert compiled["workspace_data_compact_sha256"] == digest(raw_data)
    assert compiled["data_compact_sha256"] != compiled["workspace_data_compact_sha256"]


@pytest.mark.parametrize("field", ["archive", "background", "patchset", "canonical"])
def test_identity_mismatch_rejected(tmp_path, field):
    document, _, _ = fixture(tmp_path)
    if field == "archive":
        document["archive"]["sha256"] = "0" * 64
    elif field == "canonical":
        document["expected_background_digest"] = "0" * 64
    else:
        document["members"][field]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differ|mismatch"):
        oracle.load_published_model(document)


@pytest.mark.parametrize("coordinate", ["225", 225.0000001, True, float("inf")])
def test_no_fuzzy_or_untyped_coordinate_substitution(tmp_path, coordinate):
    document, _, _ = fixture(tmp_path)
    document["coordinates"]["mass"] = coordinate
    with pytest.raises(ValueError, match="absent|coordinates"):
        oracle.load_published_model(document)


def test_duplicate_coordinates_rejected_even_if_requested_is_unique(tmp_path):
    def duplicate(_, patchset):
        patchset["patches"].extend([deepcopy(patchset["patches"][0]), deepcopy(patchset["patches"][0])])
        patchset["patches"][1]["metadata"]["values"][1] = 220
        patchset["patches"][2]["metadata"]["values"][1] = 220.0
    document, _, _ = fixture(tmp_path, change=duplicate)
    with pytest.raises(ValueError, match="duplicate exact typed"):
        oracle.load_published_model(document)


def test_coordinate_equality_uses_documented_binary_json_number_semantics(tmp_path):
    document, _, _ = fixture(tmp_path)
    # The contract explicitly retains Python binary-number semantics, rather
    # than arbitrary decimal-token precision or nearest-neighbor matching.
    raw = json.dumps(document).replace('"mass": 225', '"mass": 225.00000000000000001')
    admitted = oracle._json(raw)
    assert admitted["coordinates"]["mass"] == 225.0
    contract = oracle.load_published_model(admitted)
    assert contract.manifest()["patch_index"] == 0
    assert contract.manifest()["coordinates"]["mass"] == 225.0


@pytest.mark.parametrize("path", ["/channels/1٠/samples/0", "/channels/0/samples/1٠",
                                  "/channels/01/samples/0", "/channels/0/samples/01"])
def test_noncanonical_array_indices_rejected_before_signal_insertion(tmp_path, path):
    def change(background, patchset):
        # Make index ten valid, so refusal tests spelling rather than range.
        for index in range(2, 11):
            channel = deepcopy(background["channels"][1])
            channel["name"] = "C" + str(index)
            background["channels"].append(channel)
            background["observations"].append({"name": channel["name"], "data": [20]})
        for index in range(1, 11):
            sample = deepcopy(background["channels"][0]["samples"][0])
            sample["name"] = "background" + str(index)
            background["channels"][0]["samples"].append(sample)
        patchset["patches"][0]["patch"][0]["path"] = path
    document, _, _ = fixture(tmp_path, change=change)
    with pytest.raises(ValueError, match="exact signal-sample add operations"):
        oracle.load_published_model(document)


def test_ascii_multidigit_index_and_append_preserve_signal_insertion(tmp_path):
    def change(background, patchset):
        for index in range(2, 11):
            channel = deepcopy(background["channels"][1])
            channel["name"] = "C" + str(index)
            background["channels"].append(channel)
            background["observations"].append({"name": channel["name"], "data": [20]})
        signal = patchset["patches"][0]["patch"][0]
        for index in range(1, 11):
            sample = deepcopy(background["channels"][10]["samples"][0])
            sample["name"] = "background" + str(index)
            background["channels"][10]["samples"].append(sample)
        signal["path"] = "/channels/10/samples/10"
        appended = deepcopy(signal)
        appended["path"] = "/channels/0/samples/-"
        patchset["patches"][0]["patch"].append(appended)
    document, _, _ = fixture(tmp_path, change=change)
    contract = oracle.load_published_model(document)
    assert contract.workspace()["channels"][10]["samples"][10]["name"] == "signal"
    assert contract.workspace()["channels"][0]["samples"][-1]["name"] == "signal"


@pytest.mark.parametrize("operation", [
    {"op": "replace", "path": "/observations/0/data", "value": [1]},
    {"op": "add", "path": "/channels/9/samples/0", "value": {}},
    {"op": "add", "path": "/channels/0/samples/2", "value": {}},
])
def test_background_edit_or_invalid_insertion_not_admitted(tmp_path, operation):
    def change(_, patchset):
        patchset["patches"][0]["patch"] = [operation]
    document, _, _ = fixture(tmp_path, change=change)
    with pytest.raises(ValueError, match="add operations|outside"):
        oracle.load_published_model(document)


def test_explicit_measurement_selection(tmp_path):
    def change(background, _):
        background["measurements"].append({"name": "N", "config": {"poi": "mu", "parameters": [{"name": "mu", "inits": [2.0]}]}})
    document, _, _ = fixture(tmp_path, change=change)
    document["measurement"] = "N"
    model, _, compiled = oracle.compile_published_model(oracle.load_published_model(document))
    assert model.config.suggested_init()[model.config.poi_index] == 2
    assert compiled["measurement"]["name"] == "N"
    document["measurement"] = "missing"
    with pytest.raises(ValueError, match="measurement"):
        oracle.load_published_model(document)


def test_missing_channel_observation(tmp_path):
    def change(background, _):
        background["observations"] = background["observations"][:1]
    document, _, _ = fixture(tmp_path, change=change)
    with pytest.raises(ValueError, match="observations"):
        oracle.load_published_model(document)


def test_incompatible_parameter_types_rejected_by_pyhf(tmp_path):
    def change(_, patchset):
        patchset["patches"][0]["patch"][0]["value"]["modifiers"][1] = {"name": "shared", "type": "normsys", "data": {"hi": 1.1, "lo": 0.9}}
    document, _, _ = fixture(tmp_path, change=change)
    import pyhf
    contract = oracle.load_published_model(document)
    with pytest.raises(pyhf.exceptions.InvalidNameReuse):
        oracle.compile_published_model(contract)


def test_compatible_cross_type_parameter_name_sharing(tmp_path):
    def change(background, patchset):
        background["channels"][0]["samples"][0]["modifiers"] = [{"name": "shared", "type": "normsys", "data": {"hi": 1.1, "lo": 0.9}}]
        patchset["patches"][0]["patch"][0]["value"]["modifiers"][1] = {"name": "shared", "type": "histosys", "data": {"hi_data": [5.0], "lo_data": [3.0]}}
    document, _, _ = fixture(tmp_path, change=change)
    contract = oracle.load_published_model(document)
    shared = next(row for row in contract.manifest()["parameter_name_sharing"] if row["name"] == "shared")
    assert shared["types"] == ["histosys", "normsys"] and shared["shared_with_background"]
    model, _, compiled = oracle.compile_published_model(contract)
    assert model.config.param_set("shared").n_parameters == 1
    assert compiled["constraints"]["shared"]["constrained"]


def test_nonpoi_addition_cannot_be_mislabelled_signal(tmp_path):
    def change(_, patchset):
        patchset["patches"][0]["patch"][0]["value"]["modifiers"] = []
    document, _, _ = fixture(tmp_path, change=change)
    with pytest.raises(ValueError, match="POI normfactor"):
        oracle.load_published_model(document)


def test_source_record_reference_mismatch_rejected(tmp_path):
    document, _, _ = fixture(tmp_path)
    document["source"]["record_id"] = "ins0"
    with pytest.raises(ValueError, match="source record"):
        oracle.load_published_model(document)


def test_archive_snapshot_is_consumed_after_pin(tmp_path, monkeypatch):
    document, _, _ = fixture(tmp_path)
    original = oracle._bound_path
    def replace_after_admission(pin, base, limit):
        path, raw = original(pin, base, limit)
        path.write_bytes(b"replaced path after snapshot")
        return path, raw
    monkeypatch.setattr(oracle, "_bound_path", replace_after_admission)
    contract = oracle.load_published_model(document)
    assert contract.manifest()["archive"]["sha256"] == document["archive"]["sha256"]
    assert contract.manifest()["signal"][0]["nominal"] == [4]


def test_oversized_declared_archive_rejected_before_payload(tmp_path):
    document, _, _ = fixture(tmp_path)
    archive = tmp_path / "bomb.tar.gz"
    member = tarfile.TarInfo("oversized")
    member.size = oracle.MAX_ARCHIVE_EXPANDED_BYTES + 1
    archive.write_bytes(gzip.compress(member.tobuf() + bytes(1024)))
    document["archive"] = {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="expanded bytes"):
        oracle.load_published_model(document)


def test_inventory_binds_grounding_without_inference(tmp_path, monkeypatch):
    document, _, _ = fixture(tmp_path)
    grounding = tmp_path / "record.json"
    grounding.write_text('{"version":1}')
    document["grounding"] = [{"path": grounding.name, "sha256": hashlib.sha256(grounding.read_bytes()).hexdigest()}]
    source = tmp_path / "input.json"
    source.write_text(json.dumps(document))
    monkeypatch.setattr(oracle, "compile_published_model", lambda *_: pytest.fail("inventory compiled a model"))
    assert oracle.inputs({"input": source.name}, tmp_path) == [source, tmp_path / "model.tar.gz", grounding]
    grounding.write_text('{"version":2}')
    with pytest.raises(ValueError, match="source bytes differ"):
        oracle.inputs({"input": source.name}, tmp_path)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'])
def test_ambiguous_or_nonfinite_json_rejected(raw):
    with pytest.raises(ValueError):
        oracle._json(raw)
