"""Cross-check the shared production registries against controller route providers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ravel.controller.routes.ml import staged as ml_staged
from ravel.controller.step import operations as step_operations
from ravel.controller.routes.manuscript import staged as manuscript_staged

DATA = Path(__file__).resolve().parents[3] / "src/ravel/data"


def _closed_signature(value):
    """Project provider-specific basis labels into the closed request-plan vocabulary."""
    result = copy.deepcopy(value)
    allowed = {"generated_prediction", "simulated_acceptance", "published_statistical_model",
               "reimplemented_statistical_model", "constructed_statistical_model", "published_results",
               "supplied_inputs", "observed_data", "analytic", "numerical_solver", "trained_model",
               "authored_code", "unclassified"}
    for row in result["basis"]["adds"]:
        if row["element"] not in allowed:
            row.clear()
            row["element"] = "unclassified"
    return result


def _read(relative):
    return json.loads((DATA / relative).read_text())


def test_every_staged_route_operation_has_its_provider_signature_and_executor():
    signatures = _read("operation_signatures.json")["operations"]
    executors = _read("roles/executors.json")["operations"]

    staged_signatures = {
        **ml_staged.signatures(),
        **manuscript_staged.signatures(),
    }
    staged_executors = {
        **ml_staged.executors(),
        **manuscript_staged.executors(),
    }
    assert {name: signatures[name] for name in staged_signatures} == {
        name: _closed_signature(value) for name, value in staged_signatures.items()
    }
    assert {name: executors[name] for name in staged_executors} == staged_executors


def test_study_operations_and_released_untyped_executors_are_registered():
    signatures = _read("operation_signatures.json")["operations"]
    executors = _read("roles/executors.json")["operations"]
    roles = _read("roles/registry.json")["roles"]

    expected = {
        "scoped-generate": "shower-detector",
        "scoped-likelihood": "inference",
    }
    for operation, role in expected.items():
        assert operation in signatures
        assert executors[operation] == role
        assert operation in roles[role]["card"]["operations"]

    # The study preparation evaluates no scientific input: a registered host planning operation with its stated
    # reason, executed by no production role.
    hosts = _read("roles/executors.json")["host_operations"]
    assert "ordinary-study-prepare" in signatures and hosts["ordinary-study-prepare"]
    assert "ordinary-study-prepare" not in executors

    # These public executors remain available; the registry supplies their typed contracts.
    assert executors["inference"] == "inference"
    assert executors["detector-calibration"] == "detector-calibrator"
    assert {"inference", "detector-calibration"} <= signatures.keys()


def test_route_operations_and_role_outputs_resolve_against_the_shared_registries():
    signature_doc = _read("operation_signatures.json")
    executor_doc = _read("roles/executors.json")
    registry = _read("roles/registry.json")
    signatures = signature_doc["operations"]
    executors = executor_doc["operations"]
    hosts = executor_doc["host_operations"]

    routes = DATA / "controller/routes"
    checked = 0
    for path in sorted(routes.glob("*.json")):
        document = json.loads(path.read_text())
        for spec in document.get("specs", [document]):
            for step in spec.get("steps", []):
                operation = step.get("operation")
                if not operation:
                    continue
                checked += 1
                assert operation in signatures or operation in hosts, (path.name, operation)
                role = executors.get(operation)
                if role:
                    assert role in registry["roles"], (path.name, operation, role)
                    assert operation in registry["roles"][role]["card"]["operations"], (path.name, operation, role)
                signature = signatures.get(operation)
                if signature is None:
                    continue
                # The admission the governed step applies: every declared output and input kind is in the signature.
                produced = {slot["kind"] for slot in signature["produces"]}
                consumed = {slot["kind"] for slot in signature["consumes"]}
                for row in step.get("outputs", []):
                    assert row["kind"] in produced, (path.name, step["id"], row)
                for row in step.get("inputs", []):
                    assert not consumed or row["kind"] in consumed, (path.name, step["id"], row)
    assert checked > 0

    output_dir = DATA / "roles/schema/outputs"
    for role, entry in registry["roles"].items():
        card = entry["card"]
        schema = card.get("output", {}).get("schema")
        if schema:
            assert (output_dir / f"{schema}.json").is_file(), (role, schema)


def test_analysis_context_inputs_are_optional_typed_slots():
    operations = _read("operation_signatures.json")["operations"]
    expected = {
        "acquire-published": {"context_document": "document"},
        "analysis-lifecycle": {"point": "parameter_point", "context_document": "document",
                               "context_table": "table"},
        "figure-comparison": {"context_cutflow": "cutflow", "context_document": "document"},
        "lifecycle-routine-recast": {"point": "parameter_point", "context_document": "document"},
    }
    for operation, slots in expected.items():
        declared = {row["slot"]: row for row in operations[operation]["consumes"]}
        for slot, kind in slots.items():
            assert declared[slot]["kind"] == kind
            assert declared[slot]["optional"] is True


def test_E04_every_route_operation_and_context_slot_passes_real_peer_admission():
    signatures = step_operations.signatures()
    context_slots = {
        "acquire-published": {"context_document": "document"},
        "analysis-lifecycle": {"point": "parameter_point", "context_document": "document",
                               "context_table": "table"},
        "figure-comparison": {"context_cutflow": "cutflow", "context_document": "document"},
        "lifecycle-routine-recast": {"point": "parameter_point", "context_document": "document"},
    }
    for operation, slots in context_slots.items():
        signature = signatures[operation]
        step = {"id": "fixture-step", "kind": "operate", "operation": operation,
                "outputs": [{"path": "outputs/result.json", "kind": signature["produces"][0]["kind"]}],
                "parameters": {"effects": [], "task": {"max_bytes": 0, "max_seconds": 0}}}
        inputs = [{"artifact": f"context:{slot}", "kind": kind} for slot, kind in slots.items()]
        assert step_operations.admission_errors(step, inputs_custody=inputs, signature=signature) == []
        inputs.append({"artifact": "context:undeclared", "kind": "undeclared_fixture_kind"})
        assert step_operations.admission_errors(step, inputs_custody=inputs, signature=signature)[0]["code"] == \
            "operation_artifact_undeclared"


def test_public_registry_baseline_is_retained():
    signatures = _read("operation_signatures.json")["operations"]
    executors = _read("roles/executors.json")["operations"]
    assert {"analyze", "inference", "detector-calibration"} <= signatures.keys()
    assert {"analyze", "inference", "detector-calibration"} <= executors.keys()


LITERATURE_MODEL_CALL_ROLES = ("literature-query-expander", "literature-evidence-scorer", "literature-discovery-selector")


def test_literature_route_roles_resolve_through_the_composed_registry():
    from ravel.controller.step import cards as step_cards
    from ravel.workflow import literature_discovery_agent, literature_evidence_scoring, literature_query
    from ravel.workflow import literature_roles, literature_serving, role_registry, toolbelt

    raw = _read("roles/registry.json")["roles"]
    document = role_registry.registry_document()
    # Each module's governed call names its card; the card comes from its append-only registration fragment.
    assert {literature_query.ROLE, literature_evidence_scoring.ROLE, literature_discovery_agent.ROLE} == set(
        LITERATURE_MODEL_CALL_ROLES)
    for role in LITERATURE_MODEL_CALL_ROLES:
        assert role not in raw
        assert document["roles"][role] == _read(f"roles/registration/{role}.json")["roles"][role]
        card = role_registry.load(role)
        assert role_registry.validate_card(card) == []
        # The final record of a dispatched seat is the active producer form, which the controller maps;
        # the module's model-call reply keeps its own closed request-bound schema.
        assert card["output"]["schema"] == "producer.v1" and "handoff" in toolbelt.output_schema(card)["properties"]
        assert step_cards.controller_schema(card)
        assert card["sees"]["profile"] == "blind" and card["requires"]["blind"] is True
        assert literature_roles.operations(card) == ()
    # The scout is registered in the base registry; it alone declares the four served operations.
    assert "literature-scout" in raw
    for card in role_registry.all_cards():
        declared = literature_roles.operations(card)
        assert declared == (tuple(literature_serving.TOOL_NAMES) if card["id"] == "literature-scout" else ())


def test_every_composed_registry_role_output_schema_resolves():
    from ravel.workflow import role_registry

    output_dir = DATA / "roles/schema/outputs"
    for role, entry in role_registry.registry_document()["roles"].items():
        schema = role_registry.load(role).get("output", {}).get("schema")
        assert schema and (output_dir / f"{schema}.json").is_file(), (role, schema)
