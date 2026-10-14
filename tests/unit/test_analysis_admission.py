"""Open admission checks reject stale scopes and incomplete output denominators."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil

import pytest

from ravel.workflow import analysis_admission as admission


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path, purpose="routine-evaluation", input_level="reconstructed", target_level="reconstructed"):
    artifacts = []
    for name, role in [("implementation", "source"), ("events", "events"), ("paper", "paper"), ("host", "review-host")]:
        path = tmp_path / (name + ".txt")
        path.write_text("Frozen engineering control " + name + "\n")
        artifacts.append({"id": name, "path": path.name,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "role": role})
    return {"schema_version": 1, "kind": "analysis_specification",
            "analysis_id": "uncatalogued:CMS-control-with-source-booked-bins",
            "implementation": {"framework": "cpp", "routine": "Control", "artifact": "implementation"},
            "request": {"purpose": purpose, "input_level": input_level, "target_level": target_level,
                        "scope": {"model": "control", "era": "frozen", "target": "synthetic boundary calculation"}},
            "artifacts": artifacts, "subjects": ["implementation", "events", "paper"],
            "definitions": [{"id": "cut", "role": "selection", "definition": "pT strictly greater than 30 GeV",
                             "artifact": "paper", "locator": "engineering control line 1"}],
            "outputs": [{"name": "SR", "quantity": "yield", "unit": "events", "normalization": "absolute",
                         "representation": "integrated", "weight": "nominal", "definition": "cut", "bin": None}], "checks": []}


def artifact(tmp_path, spec, identity, value, role="check"):
    path = tmp_path / (identity + ".json")
    digest = write(path, value)
    spec["artifacts"].append({"id": identity, "path": path.name, "sha256": digest, "role": role})
    return path


def receipt(spec, kind, identity=None, context=None):
    value = {"schema_version": 1, "kind": "analysis_check_receipt", "check": kind,
             "analysis_id": spec["analysis_id"], "scope_sha256": admission._digest(spec["request"]["scope"]),
             "request_sha256": admission._digest(spec["request"]),
             "implementation_sha256": admission._digest(spec["implementation"]),
             "subjects": admission._binding(spec), "definitions_sha256": admission._digest(spec["definitions"]),
             "outputs_sha256": admission._digest(spec["outputs"]), "status": "passed",
             "producer": {"identity": identity or ("engineering-control-" + kind),
                          "context_id": context or ("isolated-control-" + kind),
                          "role": "independent-verifier" if kind == "independent-review" else "checker"},
             "method": "frozen source-bound structural control", "limitations": ["synthetic control only"]}
    if kind == "independent-review":
        value["host_receipt"] = "host"
    return value


def complete(tmp_path, spec):
    for kind in admission.requirements(spec):
        if kind == "reference":
            continue
        artifact(tmp_path, spec, "check-" + kind, receipt(spec, kind))
        spec["checks"].append({"kind": kind, "method": "receipt", "artifact": "check-" + kind})
    if "reference" in admission.requirements(spec):
        comparison(tmp_path, spec)
    return spec


def comparison(tmp_path, spec, prediction=4, reference=4, rtol=0, atol=0):
    def values(number, prediction):
        return {"schema_version": 1, "kind": "analysis_reference_values", "analysis_id": spec["analysis_id"],
                "scope_sha256": admission._digest(spec["request"]["scope"]),
                "request_sha256": admission._digest(spec["request"]),
                "implementation_sha256": admission._digest(spec["implementation"]),
                "definitions_sha256": admission._digest(spec["definitions"]),
                "subjects": admission._binding(spec) if prediction else {"paper": spec["artifacts"][2]["sha256"]},
                "source": "synthetic candidate" if prediction else "frozen independent arithmetic control",
                "outputs": [{"basis": deepcopy(spec["outputs"][0]), "value": number}]}
    artifact(tmp_path, spec, "prediction", values(prediction, True))
    artifact(tmp_path, spec, "reference", values(reference, False))
    spec["checks"].append({"kind": "reference", "method": "comparison", "prediction": "prediction",
                           "reference": "reference", "criteria": {"rtol": rtol, "atol": atol}})


def assess(tmp_path, spec):
    write(tmp_path / "analysis.json", spec)
    return admission.assess({"specification": "analysis.json"}, tmp_path)


def mutate_artifact(tmp_path, spec, identity, mutate):
    fact = next(a for a in spec["artifacts"] if a["id"] == identity)
    path = tmp_path / fact["path"]
    data = json.loads(path.read_text())
    mutate(data)
    fact["sha256"] = write(path, data)


def test_uncatalogued_identity_is_open_but_no_checks_never_means_support(tmp_path):
    spec = fixture(tmp_path)
    result = assess(tmp_path, spec)
    assert result["status"] == "blocked"
    assert len(result["obligations"]) == 4
    assert result["physics_validated"] is False
    assert result["admitted_action"] == "inspect-source-bound-evidence"


def test_complete_engineering_census_cannot_certify_detector_or_serve_exclusion(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path))
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is True
    assert result["physics_validated"] is False
    assert result["scientific_certification"] == "requires-authoritative-review"
    assert "response" not in result["required_checks"]


def test_truth_input_to_detector_exclusion_still_requires_response(tmp_path):
    spec = fixture(tmp_path, purpose="exclusion", input_level="truth", target_level="reconstructed")
    assert {"response", "uncertainty", "statistics", "independent-review"} <= set(admission.requirements(spec))
    spec["request"]["target_level"] = "particle"
    assert "response" not in admission.requirements(spec)


@pytest.mark.parametrize("purpose,required", [("projection", "projection-calibration"), ("method-study", "method-calibration")])
def test_new_physics_question_derives_its_own_calibration_obligation(tmp_path, purpose, required):
    spec = fixture(tmp_path, purpose=purpose)
    assert required in admission.requirements(spec)
    assert "independent-review" in admission.requirements(spec)


def test_actual_complete_output_comparison_matches_frozen_values(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path, purpose="reference-reproduction"))
    result = assess(tmp_path, spec)
    check = next(c for c in result["checks"] if c["kind"] == "reference")
    assert check["status"] == "passed" and check["outputs"][0]["difference"] == 0
    assert result["evidence_complete"] is True


def test_numeric_reference_failure_is_retained_and_blocks_admission(tmp_path):
    spec = fixture(tmp_path, purpose="reference-reproduction")
    comparison(tmp_path, spec, prediction=4, reference=6, rtol=0.1)
    result = assess(tmp_path, spec)
    check = result["checks"][0]
    assert check["status"] == "failed" and check["outputs"][0]["difference"] == -2
    assert check["outputs"][0]["tolerance"] == pytest.approx(0.6)
    assert any(o["kind"] == "reference" for o in result["obligations"])


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["outputs"].clear(), "omitted requested outputs"),
    (lambda d: d["outputs"][0]["basis"].update(unit="pb"), "basis differs"),
    (lambda d: d["outputs"][0]["basis"].update(weight="pdf-1"), "basis differs"),
    (lambda d: d["outputs"][0]["basis"].update(normalization="conditional"), "basis differs"),
    (lambda d: d.update(scope_sha256="0" * 64), "physical scope"),
    (lambda d: d.update(subjects={"invented-public-source": "0" * 64}), "fictional, stale or unbound"),
])
def test_reference_cannot_borrow_other_units_weights_scopes_or_fictional_source(tmp_path, mutate, message):
    spec = fixture(tmp_path, purpose="reference-reproduction")
    comparison(tmp_path, spec)
    mutate_artifact(tmp_path, spec, "reference", mutate)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert message in result["checks"][0]["reason"]


@pytest.mark.parametrize("prediction,reference,rtol", [(1e308, -1e308, 0), (1e308, 1e308, 1e308)])
def test_finite_inputs_cannot_overflow_into_successful_comparison(tmp_path, prediction, reference, rtol):
    spec = fixture(tmp_path, purpose="reference-reproduction")
    comparison(tmp_path, spec, prediction, reference, rtol)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "derived comparison" in result["checks"][0]["reason"]
    assert result["evidence_complete"] is False


def test_oversized_finite_integer_value_is_a_failed_check_not_conversion_crash(tmp_path):
    spec = fixture(tmp_path, purpose="reference-reproduction")
    comparison(tmp_path, spec, prediction=10 ** 600)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "invalid reference value" in result["checks"][0]["reason"]


@pytest.mark.parametrize("change", ["subjects", "definitions", "outputs", "scope"])
def test_receipt_cannot_survive_scientific_basis_change(tmp_path, change):
    spec = complete(tmp_path, fixture(tmp_path))
    if change == "subjects":
        # Definition sources are now compulsory in the effective closure even
        # if the caller omits their IDs. Change a genuinely optional subject.
        spec["subjects"].remove("events")
    elif change == "definitions":
        spec["definitions"][0]["definition"] = "pT greater than or equal to 30 GeV"
    elif change == "outputs":
        spec["outputs"][0]["weight"] = "scale-up"
    else:
        spec["request"]["scope"]["era"] = "unvalidated new era"
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is False
    assert all(c["status"] == "failed" for c in result["checks"])


def test_hash_custody_rechecked_and_symlink_rejected(tmp_path):
    spec = fixture(tmp_path)
    (tmp_path / "implementation.txt").write_text("changed source\n")
    with pytest.raises(ValueError, match="changed artifact"):
        assess(tmp_path, spec)
    (tmp_path / "implementation.txt").unlink()
    (tmp_path / "implementation.txt").symlink_to(tmp_path / "paper.txt")
    refusal = f"input path traverses a symlink: {tmp_path / 'implementation.txt'}"
    with pytest.raises(ValueError, match=re.escape(refusal)):
        assess(tmp_path, spec)


@pytest.mark.parametrize("reuse", ["identity", "context"])
def test_verifier_cannot_reuse_producer_actor_or_context(tmp_path, reuse):
    spec = complete(tmp_path, fixture(tmp_path, purpose="exclusion"))
    existing = receipt(spec, "definitions")["producer"]
    def mutate(data):
        field = "identity" if reuse == "identity" else "context_id"
        data["producer"][field] = existing[field]
    mutate_artifact(tmp_path, spec, "check-independent-review", mutate)
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is False
    assert any("identity or context" in o.get("reason", "") for o in result["obligations"])


def test_independent_review_requires_bound_host_evidence(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path, purpose="exclusion"))
    mutate_artifact(tmp_path, spec, "check-independent-review", lambda d: d.update(host_receipt="paper"))
    result = assess(tmp_path, spec)
    assert next(c for c in result["checks"] if c["kind"] == "independent-review")["status"] == "failed"
    assert result["physics_validated"] is False


def test_dummy_bound_host_json_cannot_advance_independent_review(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path, purpose="exclusion"))
    result = assess(tmp_path, spec)
    review = next(c for c in result["checks"] if c["kind"] == "independent-review")
    assert review["status"] == "unknown"
    assert review["host_invocation_verified"] is False
    assert result["evidence_complete"] is False
    assert any(o["kind"] == "independent-review" and o["status"] == "unknown" for o in result["obligations"])


def test_stale_host_subject_assertion_cannot_close_current_review(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path, purpose="exclusion"))
    fact = next(a for a in spec["artifacts"] if a["id"] == "host")
    path = tmp_path / fact["path"]
    fact["sha256"] = write(path, {"subjects": {"implementation": "0" * 64}, "status": "passed"})
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is False
    assert next(c for c in result["checks"] if c["kind"] == "independent-review")["status"] == "unknown"


def graph_check(tmp_path, spec):
    artifact(tmp_path, spec, "review-subject", admission.review_subject(spec), role="review-subject")
    check = {"kind": "independent-review", "method": "graph-model", "graph": str(tmp_path / "graph"),
             "node_id": "verifier", "subject": "review-subject", "packet_sha256": "a" * 64}
    spec["checks"].append(check)
    return check


def test_graph_review_rejects_stale_full_subject_before_host_lookup(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion")
    graph_check(tmp_path, spec)
    spec["request"]["target_level"] = "particle"
    monkeypatch.setattr(agent_graph, "model_receipt", lambda *a, **k: pytest.fail("stale subject reached host verifier"))
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "current request/implementation" in result["checks"][0]["reason"]


def test_graph_subject_binds_definition_source_even_outside_listed_subjects(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion")
    spec["subjects"].remove("paper")
    graph_check(tmp_path, spec)
    paper = next(a for a in spec["artifacts"] if a["id"] == "paper")
    (tmp_path / paper["path"]).write_text("Changed definition source bytes\n")
    paper["sha256"] = hashlib.sha256((tmp_path / paper["path"]).read_bytes()).hexdigest()
    monkeypatch.setattr(agent_graph, "model_receipt", lambda *a, **k: pytest.fail("changed source reached host verifier"))
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "current request/implementation" in result["checks"][0]["reason"]


def test_receipt_binds_definition_source_even_outside_listed_subjects(tmp_path):
    spec = fixture(tmp_path)
    spec["subjects"].remove("paper")
    complete(tmp_path, spec)
    assert assess(tmp_path, spec)["evidence_complete"] is True
    paper = next(a for a in spec["artifacts"] if a["id"] == "paper")
    (tmp_path / paper["path"]).write_text("Changed definition evidence\n")
    paper["sha256"] = hashlib.sha256((tmp_path / paper["path"]).read_bytes()).hexdigest()
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is False
    assert all(c["status"] == "failed" for c in result["checks"])


def test_graph_subject_binds_nonreview_evidence_and_comparison_criteria(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion")
    comparison(tmp_path, spec)
    graph_check(tmp_path, spec)
    spec["checks"][0]["criteria"]["atol"] = 100
    monkeypatch.setattr(agent_graph, "model_receipt", lambda *a, **k: pytest.fail("changed criteria reached host verifier"))
    result = assess(tmp_path, spec)
    assert next(c for c in result["checks"] if c["kind"] == "independent-review")["status"] == "failed"


def test_actual_unexecuted_graph_node_cannot_close_review(tmp_path):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion")
    check = graph_check(tmp_path, spec)
    packet = tmp_path / "packet"; packet.mkdir()
    graph_spec = {"schema_version": 1, "graph_id": "admission-pending-control",
                  "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": 64,
                             "max_wall_seconds": 60, "max_reworks": 0},
                  "nodes": [{"id": "verifier", "kind": "model", "role": "verifier", "depends_on": [], "inputs": [],
                             "packet": {"path": str(packet), "manifest_sha256": check["packet_sha256"]},
                             "action": "external", "parameters": {}, "max_attempts": 1}]}
    agent_graph.create(check["graph"], graph_spec)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "not complete" in result["checks"][0]["reason"]
    assert result["evidence_complete"] is False


def synthetic_host(spec, *, observation="control_only"):
    """Unit-only boundary data; never presented as a live model observation."""
    return {"node_id": "verifier", "request_id": "unique-host-request", "limitations": ["synthetic boundary control"],
            "execution_observation": observation, "context_transport_separated": True,
            "exact_subject_presented": True}


def test_source_projection_metadata_cannot_substitute_for_presented_full_subject(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion"); graph_check(tmp_path, spec)
    host = synthetic_host(spec, observation="host_attested_external")
    host["exact_subject_presented"] = False
    def projection(*args, **kwargs):
        assert kwargs["require_exact_subject"] is True
        return host
    monkeypatch.setattr(agent_graph, "model_receipt", projection)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert "exact current full subject bytes" in result["checks"][0]["reason"]


def test_loopback_control_transport_stays_unknown_even_with_separated_context(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion"); graph_check(tmp_path, spec)
    monkeypatch.setattr(agent_graph, "model_receipt", lambda *a, **k: synthetic_host(spec))
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "unknown"
    assert result["checks"][0]["host_invocation_verified"] is False
    assert result["evidence_complete"] is False


def test_changed_public_verdict_or_preserved_finding_cannot_be_pass_vote(tmp_path, monkeypatch):
    from ravel.workflow import agent_graph
    spec = fixture(tmp_path, purpose="exclusion"); graph_check(tmp_path, spec)
    subject = next(a for a in spec["artifacts"] if a["id"] == "review-subject")
    value = {"schema_version": 1, "kind": "analysis_review_verdict", "analysis_id": spec["analysis_id"],
             "subject_sha256": subject["sha256"], "status": "passed", "findings": [{"id": "missing-response", "summary": "Response is unavailable"}],
             "limitations": ["unit-only boundary control"]}
    host = synthetic_host(spec, observation="remote_transport_observed")
    host.update(public_value=value, public_value_sha256="0" * 64)
    monkeypatch.setattr(agent_graph, "model_receipt", lambda *a, **k: host)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed" and "digest" in result["checks"][0]["reason"]
    host["public_value_sha256"] = admission._digest(value)
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "blocked"
    assert result["checks"][0]["findings"][0]["id"] == "missing-response"
    assert result["physics_validated"] is False


def test_supplied_material_failure_is_not_dropped_for_narrow_task(tmp_path):
    spec = complete(tmp_path, fixture(tmp_path))
    data = receipt(spec, "response"); data["status"] = "failed"
    artifact(tmp_path, spec, "bad-response", data)
    spec["checks"].append({"kind": "response", "method": "receipt", "artifact": "bad-response"})
    result = assess(tmp_path, spec)
    assert result["evidence_complete"] is False
    assert any(o["kind"] == "response" for o in result["obligations"])


def test_duplicate_requested_outputs_and_checks_rejected(tmp_path):
    spec = fixture(tmp_path)
    spec["outputs"].append(deepcopy(spec["outputs"][0]))
    with pytest.raises(ValueError, match="duplicate requested output"):
        admission.validate_specification(spec)


@pytest.mark.parametrize("mutation", ["request", "definition", "geometry"])
def test_reference_cannot_survive_request_definition_or_bin_geometry_change(tmp_path, mutation):
    spec = fixture(tmp_path, purpose="reference-reproduction")
    spec["outputs"][0]["bin"] = {"axes": [{"name": "mjj", "unit": "GeV", "lower": 1000, "upper": 1200}]}
    comparison(tmp_path, spec)
    if mutation == "request":
        spec["request"]["purpose"] = "exclusion"
    elif mutation == "definition":
        spec["definitions"][0]["definition"] = "Changed selection threshold"
    else:
        mutate_artifact(tmp_path, spec, "reference", lambda d: d["outputs"][0]["basis"]["bin"]["axes"][0].update(upper=1400))
    result = assess(tmp_path, spec)
    assert result["checks"][0]["status"] == "failed"
    assert result["evidence_complete"] is False


def test_differential_quantity_cannot_omit_bin_geometry(tmp_path):
    spec = fixture(tmp_path)
    spec["outputs"][0]["representation"] = "differential"
    with pytest.raises(ValueError, match="explicit bin geometry"):
        admission.validate_specification(spec)


def test_inputs_and_cli_are_read_only_except_requested_report(tmp_path, capsys):
    spec = complete(tmp_path, fixture(tmp_path))
    path = tmp_path / "analysis.json"; write(path, spec)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert len(admission.inputs({"specification": str(path)}, tmp_path)) == len(spec["artifacts"]) + 1
    out = tmp_path / "report.json"
    assert admission.main(["--specification", str(path), "--out", str(out)]) == 0
    assert all((tmp_path / name).read_bytes() == raw for name, raw in before.items())
    assert json.loads(out.read_text())["physics_validated"] is False
    capsys.readouterr()


def test_actual_builder_receipt_consumes_layout_dependencies_and_probe_in_admission(tmp_path, monkeypatch):
    from ravel.physics import routine_build as build
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("actual C++ compiler unavailable")
    source = tmp_path / "build-source"
    (source / "include").mkdir(parents=True)
    (source / "include/value.hh").write_text("#define CONTROL_VALUE 42\n")
    (source / "main.cc").write_text('#include <cstdio>\n#include "value.hh"\nint main(){std::printf("control:%d\\n",CONTROL_VALUE);}\n')
    capsule = {"schema_version": 1, "kind": "analysis-source-capsule", "framework": "cpp", "routine": "Control",
               "source": {"repository": "supplied", "revision": None, "description": "Actual tiny build admission control"},
               "root": "build-source", "files": [{"path": name, "role": role,
                   "sha256": hashlib.sha256((source / name).read_bytes()).hexdigest()}
                   for name, role in [("main.cc", "compile"), ("include/value.hh", "header")]],
               "layout": {"include_dirs": ["include"], "asset_dirs": []},
               "dependencies": [{"name": "local header", "kind": "source", "status": "resolved",
                   "files": ["include/value.hh"], "reason": "Actual required compile-time constant"}],
               "dependency_review": {"complete": True, "description": "Complete bounded engineering fixture"}, "submodules": []}
    write(tmp_path / "capsule.json", capsule)
    config = {"schema_version": 1, "source_capsule": "capsule.json",
              "recipe": {"name": "cpp-executable", "compile_units": ["main.cc"], "output": "control", "flags": ["-std=c++17"]},
              "runtime": {"tools": {"compiler": {"path": str(Path(compiler).absolute()),
                  "sha256": hashlib.sha256(Path(compiler).read_bytes()).hexdigest()}}, "artifacts": [], "environment": {}},
              "probe": {"executable": "$BUILD_OUTPUT", "arguments": [], "expected_exit_code": 0, "stdout_contains": ["control:42"]}}
    write(tmp_path / "build.json", config)
    out = tmp_path / "actual-build"
    observed = build.run({"backend": "routine-build", "input": "build.json"}, tmp_path, out)
    spec = fixture(tmp_path)
    implementation = next(a for a in spec["artifacts"] if a["id"] == "implementation")
    implementation.update(path="capsule.json", sha256=hashlib.sha256((tmp_path / "capsule.json").read_bytes()).hexdigest())
    complete(tmp_path, spec)
    spec["checks"] = [c for c in spec["checks"] if c["kind"] != "build"]
    for identity, path in [("observed-build", out / "build-receipt.json"), ("build-plan", out / "build-plan.json"),
                           ("built-binary", out / observed["binary"]["path"])]:
        spec["artifacts"].append({"id": identity, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "role": "build"})
    spec["checks"].append({"kind": "build", "method": "build-receipt", "artifact": "observed-build",
                           "plan": "build-plan", "capsule": "implementation", "binary": "built-binary"})
    result = assess(tmp_path, spec)
    actual = next(c for c in result["checks"] if c["kind"] == "build")
    assert actual["status"] == "passed" and actual["method"] == "observed-build-receipt"
    assert actual["verification"]["binary_sha256"] == observed["binary"]["sha256"]
    assert result["evidence_complete"] is True and result["physics_validated"] is False
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: pytest.fail("admission reran compiler or probe"))
    bound = admission.inputs({"specification": "analysis.json"}, tmp_path)
    assert (out / "compiler.log") in bound and (source / "include/value.hh") in bound
    assert (out / "work/source/include/value.hh") in bound
    (out / "probe.log").write_text("changed retained process observation\n")
    result = assess(tmp_path, spec)
    assert next(c for c in result["checks"] if c["kind"] == "build")["status"] == "failed"
    assert result["evidence_complete"] is False
