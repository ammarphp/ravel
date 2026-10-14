"""Synthetic metadata schemas and exact frozen scientific-payload retention."""
import hashlib
import json

import pytest

from test_historical_context_projection import CURRENT, event, frozen, opened
from ravel.workflow import review_context as context


def pin():
    # No referenced path is opened: this is metadata shape, not authentication.
    return {"path": "/nonexistent/metadata.json", "sha256": "b" * 64, "bytes": 123}


def metadata():
    return {"schema_version": 1, "action": "submit", "review_event": event(),
            "request": pin(), "runtime_contract": pin(),
            "scope": "synthetic delivery only", "native_kernel_model_calls": 0,
            "native_calls": 0, "approval_execution_calls": 0,
            "actor_authentication": "Declared synthetic role; no authentication claim",
            "imports": {"ravel.workflow.review_context": pin()},
            "metadata_identity_queries": [{"event": "subprocess.Popen",
                    "argv": ["uname", "-p"], "scope": "metadata identity only"}],
            "elapsed_seconds": 0.5, "max_seconds": 60}


def payload():
    return {"independent_nll": -2.25, "native_amplitudes": [0, 1.5], "failed_endpoint": True}


def retain(monkeypatch, tmp_path, value):
    root = tmp_path / "current"; root.mkdir()
    raw = json.dumps(value).encode()
    row = frozen(root, "inputs/prerequisite-evidence.json", raw)
    opened(monkeypatch, root, [row])
    packet = tmp_path / "packet"
    manifest = context.create(root, "critic", packet)
    assert not manifest["omissions"]
    assert len(manifest["artifacts"]) == 1
    returned = context.read_artifact(packet, manifest["artifacts"][0]["id"],
                                     expected_manifest_sha256=manifest["sha256"])
    assert returned == raw
    assert hashlib.sha256(returned).hexdigest() == row["sha256"]


@pytest.mark.parametrize("role", ["critic", "verifier", "synthesizer"])
def test_complete_declared_metadata_envelope_omitted(monkeypatch, tmp_path, role):
    root = tmp_path / "current"; root.mkdir()
    value = metadata()
    row = frozen(root, "inputs/own-submit-receipt.json", value)
    opened(monkeypatch, root, [row])
    manifest = context.create(root, role, tmp_path / "packet")
    assert not manifest["artifacts"] and len(manifest["omissions"]) == 1
    assert manifest["omissions"][0]["source_sha256"] == row["sha256"]


@pytest.mark.parametrize("field", ["request", "runtime_contract"])
@pytest.mark.parametrize("kind", ["unknown_dict", "valid_pin_plus_payload", "nested_payload"])
def test_unknown_payload_under_custody_field_retained(monkeypatch, tmp_path, field, kind):
    value = metadata()
    if kind == "unknown_dict": value[field] = payload()
    elif kind == "valid_pin_plus_payload": value[field]["measurements"] = payload()
    else: value[field]["path"] = payload()
    retain(monkeypatch, tmp_path, value)


@pytest.mark.parametrize("location", ["imports_row", "query_row_extra", "query_argv", "query_scope"])
def test_other_nested_metadata_fields_preserve_scientific_payload(monkeypatch, tmp_path, location):
    value = metadata()
    if location == "imports_row": value["imports"]["source-measurements"] = payload()
    elif location == "query_row_extra": value["metadata_identity_queries"][0]["measurements"] = payload()
    elif location == "query_argv": value["metadata_identity_queries"][0]["argv"].append(payload())
    else: value["metadata_identity_queries"][0]["scope"] = payload()
    retain(monkeypatch, tmp_path, value)


@pytest.mark.parametrize("field", ["schema_version", "scope", "native_kernel_model_calls", "native_calls",
    "approval_execution_calls", "actor_authentication", "elapsed_seconds", "max_seconds"])
def test_scalar_metadata_fields_cannot_carry_scientific_containers(monkeypatch, tmp_path, field):
    value = metadata(); value[field] = payload()
    retain(monkeypatch, tmp_path, value)


@pytest.mark.parametrize("kind", ["boolean_schema", "boolean_size", "negative_size", "bad_hash",
    "float_counter", "boolean_counter", "negative_counter", "nan_elapsed", "inf_bound"])
def test_malformed_metadata_preserved(kind):
    value = metadata()
    if kind == "boolean_schema": value["schema_version"] = True
    elif kind == "boolean_size": value["request"]["bytes"] = True
    elif kind == "negative_size": value["request"]["bytes"] = -1
    elif kind == "bad_hash": value["request"]["sha256"] = "short"
    elif kind == "float_counter": value["native_calls"] = 0.0
    elif kind == "boolean_counter": value["native_calls"] = False
    elif kind == "negative_counter": value["native_calls"] = -1
    elif kind == "nan_elapsed": value["elapsed_seconds"] = float("nan")
    else: value["max_seconds"] = float("inf")
    assert context._review_record_custody(value, CURRENT, "critic") is None


def test_exact_size_pin_shape_supported_without_source_open():
    value = metadata()
    value["runtime_contract"]["size"] = value["runtime_contract"].pop("bytes")
    assert context._review_record_custody(value, CURRENT, "critic") is not None


def test_unknown_request_format_preserved_even_if_it_only_repeats_review():
    value = metadata()
    value["request"] = {"review": {key: value["review_event"][key] for key in
        ("role", "actor_id", "verdict", "summary", "findings", "closes", "claim_scope")}}
    assert context._review_record_custody(value, CURRENT, "critic") is None
