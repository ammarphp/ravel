"""Prospective lossless JSON transport controls; root-only execution.

Materialization uses inert supplied bytes. Qualification controls reuse the
existing explicitly inert native/approval fixture to exercise real receipt and
closure consumers. They establish software transport only, never actual native
loader, TeX, platform, scientific or publication qualification.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import publication_runtime as pr
from test_publication_runtime_v2 import LIMITS, request, qualification_fixture


def complete_document():
    leaves = {
        f"assets/{i:04d}.sty": {
            "source": {"path": f"/source/{i:04d}.sty", "sha256": f"{i:064x}",
                       "size": i + 1, "identity": [1, i + 2, 33188, i + 1, 8, 9]},
            "mode": 420,
            "links": [{"path": f"/source/alias/{i:04d}", "target": "../real",
                       "identity": [1, i + 1002, 41471, 7, 8, 9]}],
            "components": [{"path": "/source", "identity": [1, 2, 16877]}],
        }
        for i in range(40)
    }
    return {"schema_version": 1, "kind": "synthetic-complete-closure",
            "source_provenance": [{"complete_source_inventory": {
                "files": leaves, "directories": {".": {"identity": [1, 2, 16877]}}}}],
            "files": {k: {"sha256": v["source"]["sha256"], "size": v["source"]["size"],
                          "mode": v["mode"]} for k, v in leaves.items()},
            "qualification": None, "runtime_qualified": False,
            "text": "Unicode μ and newline\n", "values": [True, False, None, -2, 0.25]}


def test_default_pretty_bytes_and_complete_compact_value_are_exact():
    document = complete_document()
    old = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    compact = pr._encoded(document, compact=True)
    assert pr._encoded(document) == pr._encoded(document, compact=False) == old
    assert len(compact) < len(old)
    assert compact == (json.dumps(document, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False) + "\n").encode()
    assert json.loads(old) == json.loads(compact) == document
    assert len(json.loads(compact)["source_provenance"][0]["complete_source_inventory"]["files"]) == 40
    assert json.loads(compact)["source_provenance"] == document["source_provenance"]


@pytest.mark.parametrize("compact", [None, 0, 1, "true", []])
def test_encoding_choice_requires_boolean(compact):
    with pytest.raises(ValueError, match="Boolean"):
        pr._encoded(complete_document(), compact=compact)


@pytest.mark.parametrize("compact", [False, True])
def test_nonfinite_values_refuse_in_both_encodings(compact):
    with pytest.raises(ValueError):
        pr._encoded({"value": float("nan")}, compact=compact)


def test_compact_emission_fits_exact_bound_and_retains_intended_pin(tmp_path):
    document = complete_document()
    compact = pr._encoded(document, compact=True)
    pretty = pr._encoded(document)
    assert len(compact) < len(pretty)
    target = tmp_path / "compact.json"
    pin = pr._emit(target, document, len(compact), compact=True)
    assert target.read_bytes() == compact
    assert pin == {"path": str(target), "sha256": hashlib.sha256(compact).hexdigest(),
                   "size": len(compact)}
    assert json.loads(target.read_bytes()) == document
    with pytest.raises(ValueError, match="capacity"):
        pr._emit(tmp_path / "pretty-too-large.json", document, len(compact))
    assert not (tmp_path / "pretty-too-large.json").exists()


@pytest.mark.parametrize("compact", [False, True])
def test_metadata_bound_is_enforced_before_creation(compact, tmp_path):
    document = complete_document()
    target = tmp_path / "over-budget.json"
    with pytest.raises(ValueError, match="capacity"):
        pr._emit(target, document, len(pr._encoded(document, compact=compact)) - 1,
                 compact=compact)
    assert not target.exists()


def test_compact_metadata_still_refuses_above_full_declared_policy(tmp_path):
    maximum = LIMITS["max_metadata_bytes"]
    document = {"complete_source_provenance": "x" * maximum}
    target = tmp_path / "over-full-policy.json"
    assert len(pr._encoded(document, compact=True)) > maximum
    with pytest.raises(ValueError, match="capacity"):
        pr._emit(target, document, maximum, compact=True)
    assert not target.exists()


@pytest.mark.parametrize("compact", [False, True])
def test_emission_excludes_existing_file(compact, tmp_path):
    target = tmp_path / "retained.json"
    target.write_bytes(b"original bytes\n")
    with pytest.raises(FileExistsError):
        pr._emit(target, complete_document(), 1024 ** 2, compact=compact)
    assert target.read_bytes() == b"original bytes\n"


@pytest.mark.parametrize("compact", [False, True])
def test_emission_refuses_postwrite_readback_replacement(compact, tmp_path, monkeypatch):
    target = tmp_path / "changed.json"
    original = Path.read_bytes
    fired = False

    def replaced(path):
        nonlocal fired
        if path == target and not fired:
            fired = True
            path.write_bytes(b'{"foreign":true}\n')
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", replaced)
    with pytest.raises(ValueError, match="intended runtime emission changed"):
        pr._emit(target, complete_document(), 1024 ** 2, compact=compact)
    assert fired and original(target) == b'{"foreign":true}\n'


def test_materialize_compacts_only_closure_and_preserves_all_source_members(tmp_path):
    request_pin, out, source, req = request(tmp_path)
    inventory_path = Path(req["trees"][0]["inventory"]["path"])
    inventory_raw = inventory_path.read_bytes()
    inventory = json.loads(inventory_raw)
    result = pr.materialize(request_pin, out)
    closure_path = Path(result["closure_manifest"]["path"])
    raw = closure_path.read_bytes()
    closure = json.loads(raw)
    assert raw == pr._encoded(closure, compact=True)
    assert inventory_raw == pr._encoded(inventory)
    assert inventory_path.read_bytes() == inventory_raw
    assert closure["source_provenance"][0]["complete_source_inventory"] == inventory
    assert set(closure["files"]) == {"selected/" + key for key in inventory["files"]}
    for name, row in inventory["files"].items():
        copied = Path(result["snapshot_root"]) / "selected" / name
        assert copied.read_bytes() == Path(row["source"]["path"]).read_bytes()
        assert copied.stat().st_mode & 0o7777 == row["mode"]
    assert closure["source_provenance"][0]["complete_source_inventory"]["files"]["bin/pdflatex"]["links"][-1]["target"] == "pdftex"
    tree = Path(closure["tree_manifest"]["path"])
    assert tree.read_bytes() == pr._encoded(json.loads(tree.read_bytes()))
    assert pr.closure_inputs(result, out, LIMITS)[0] == closure
    assert result["runtime_qualified"] is False and result["scientific_acceptance"] is False
    with pytest.raises(ValueError, match="qualification"):
        pr.closure_inputs(result, out, LIMITS, require_qualified=True)


@pytest.mark.parametrize("change", ["bytes", "mode", "new-member"])
def test_compact_closure_consumer_preserves_snapshot_currentness(tmp_path, change):
    request_pin, out, _, _ = request(tmp_path)
    result = pr.materialize(request_pin, out)
    root = Path(result["snapshot_root"])
    if change == "bytes":
        Path(result["compiler"]["path"]).write_bytes(b"changed executable bytes\n")
    elif change == "mode":
        Path(result["compiler"]["path"]).chmod(0o644)
    else:
        (root / "selected/assets/foreign.sty").write_bytes(b"foreign member\n")
    with pytest.raises(ValueError):
        pr.closure_inputs(result, out, LIMITS)


def test_derived_closure_uses_compact_transport_with_original_receipt_consumer(tmp_path, monkeypatch):
    # All native and approval seams below are the existing explicitly inert fixture.
    # No serialized synthetic observation is a real platform qualification.
    _, _, runtime, result, observations, calls, _ = qualification_fixture(tmp_path, monkeypatch)
    original_path = Path(runtime["closure_manifest"]["path"])
    original_raw = original_path.read_bytes()
    original = json.loads(original_raw)
    qualified = pr.qualify(runtime["closure_manifest"], observations, tmp_path / "derived.json")
    path = Path(qualified["path"])
    raw = path.read_bytes()
    derived = json.loads(raw)
    assert raw == pr._encoded(derived, compact=True)
    assert qualified["sha256"] == hashlib.sha256(raw).hexdigest() and qualified["size"] == len(raw)
    assert {**derived, "qualification": None, "runtime_qualified": False} == original
    assert derived["qualification"]["original_snapshot"] == runtime["closure_manifest"]
    assert derived["qualification"]["observations"] == observations
    assert derived["source_provenance"] == original["source_provenance"]
    assert original_path.read_bytes() == original_raw
    consumer = {**runtime, "closure_manifest": qualified}
    assert pr.closure_inputs(consumer, tmp_path, LIMITS, require_qualified=True)[0] == derived
    assert len(calls) == 3 and result["scientific_acceptance"] is False


def test_derived_compact_emission_still_refuses_changed_original_observation(tmp_path, monkeypatch):
    _, _, runtime, _, observations, calls, _ = qualification_fixture(tmp_path, monkeypatch)
    Path(observations["compiler"]["observation"]["path"]).write_bytes(b"changed observation\n")
    target = tmp_path / "refused-derived.json"
    with pytest.raises(ValueError):
        pr.qualify(runtime["closure_manifest"], observations, target)
    assert not target.exists() and len(calls) == 3
