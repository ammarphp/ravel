"""S1-06: optional reading and request-plan pins on the schema-v1 task contract.

A contract without pins validates, fingerprints and evaluates exactly as before. Pins only
add approval inputs, so editing a pinned record after approval fails verify_pair.
"""
import json
import os

import pytest

from ravel.validation import intake_records, validate_run_state, validate_task_contract as vtc
from ravel.workflow import provenance, workflow_state

import intake_sidecar_fixtures as fx


def _legacy_approval_input_paths(rundir):
    """approval_input_paths exactly as it was before pins existed (frozen copy)."""
    rel = validate_run_state.find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json")
    paths = [os.path.join(rundir, rel or "inputs/task_contract.json"),
             os.path.join(rundir, "inputs", "checkin1.json"),
             os.path.join(rundir, "inputs", "cost_preflight.json")]
    if os.path.isfile(paths[0]):
        contract = vtc.load_contract(paths[0])
        requirements = contract.get('task_requirements', {}) if isinstance(contract, dict) else {}
        amendments = requirements.get('amendments', []) if isinstance(requirements, dict) else []
        if isinstance(amendments, list):
            for pin in amendments:
                path = pin.get('path') if isinstance(pin, dict) else None
                if isinstance(path, str) and os.path.isabs(path): paths.append(path)
    policy = os.path.join(rundir, "inputs", "physics_review_policy.json")
    if os.path.exists(policy):
        paths.append(policy)
    from ravel.workflow import scientific_autonomy
    if os.path.isfile(paths[0]): paths.extend(scientific_autonomy.input_paths(vtc.load_contract(paths[0]), rundir))
    return list(dict.fromkeys(paths))


# --------------------------------------------------------------------------- #
#  schema
# --------------------------------------------------------------------------- #

def test_pins_are_optional_closed_pin_objects_using_evaluated_keywords():
    for key in ("reading", "request_plan"):
        pin = vtc.SCHEMA["properties"][key]
        assert pin["required"] == ["path", "sha256"] and pin["additionalProperties"] is False
        assert key not in vtc.SCHEMA["required"]
    evaluated = {"type", "properties", "required", "additionalProperties", "enum", "const", "pattern", "items",
                 "minItems", "maxItems", "anyOf", "minLength", "minimum", "maximum", "exclusiveMinimum",
                 "exclusiveMaximum", "$schema", "title", "$comment"}

    def keys(schema):
        if isinstance(schema, dict):
            for key, value in schema.items():
                if key in ("properties",):
                    for sub in value.values():
                        yield from keys(sub)
                    continue
                yield key
                if key in ("items", "additionalProperties") and isinstance(value, dict):
                    yield from keys(value)
                if key == "anyOf":
                    for sub in value:
                        yield from keys(sub)
    for schema in (vtc.SCHEMA["properties"]["reading"], vtc.SCHEMA["properties"]["request_plan"],
                   *intake_records.SCHEMAS.values()):
        assert set(keys(schema)) <= evaluated


def test_contract_with_pins_validates_and_pure_validate_reads_no_file(tmp_path):
    contract, _, _ = fx.pinned_run(tmp_path / "run")
    assert vtc.validate(contract) == []
    assert vtc.validate({**contract, "reading": {"path": "inputs/missing.json", "sha256": "1" * 64},
                         "request_plan": {"path": "inputs/also-missing.json", "sha256": "2" * 64}}) == []


@pytest.mark.parametrize("change, needle", [
    (lambda c: c.pop("reading"), "request_plan requires a pinned reading"),
    (lambda c: c.__setitem__("reading", {"path": "/abs/reading.json", "sha256": "0" * 64}), "portable run-relative"),
    (lambda c: c.__setitem__("request_plan", {"path": "../plan.json", "sha256": "0" * 64}), "portable run-relative"),
    (lambda c: c.__setitem__("request_plan", dict(c["reading"])), "distinct files"),
    (lambda c: c.__setitem__("reading", {"path": "inputs/reading.json"}), "sha256"),
    (lambda c: c.__setitem__("reading", {**c["reading"], "size": 3}), "unknown field"),
])
def test_malformed_pins_fail_pure_validation(tmp_path, change, needle):
    contract, _, _ = fx.pinned_run(tmp_path / "run")
    change(contract)
    assert any(needle in e for e in vtc.validate(contract)), vtc.validate(contract)


# --------------------------------------------------------------------------- #
#  validate_pins
# --------------------------------------------------------------------------- #

def test_validate_pins_accepts_exact_records_and_is_empty_without_pins(tmp_path):
    contract, _, _ = fx.pinned_run(tmp_path / "run")
    assert vtc.validate_pins(str(tmp_path / "run"), contract) == []
    assert vtc.validate_pins(str(tmp_path / "run"), fx.contract()) == []


@pytest.mark.parametrize("damage, needle", [
    ("missing", "not a regular file"),
    ("edited", "sha256"),
    ("schema", "kind"),
    ("prompt", "prompt_sha256"),
    ("reading-pin", "does not pin the contract's reading"),
    ("span", "exact request text"),
])
def test_validate_pins_fails_closed(tmp_path, damage, needle):
    rd = tmp_path / "run"
    contract, reading, plan = fx.pinned_run(rd)
    if damage == "missing":
        (rd / "inputs/plan.json").unlink()
    elif damage == "edited":
        (rd / "inputs/reading.json").write_text((rd / "inputs/reading.json").read_text() + " ")
    else:
        if damage == "schema":
            plan["kind"] = "request-pln"
        elif damage == "prompt":
            plan["prompt_sha256"] = "f" * 64
        elif damage == "reading-pin":
            plan["reading"] = {"path": "inputs/reading.json", "sha256": "e" * 64}
        elif damage == "span":
            reading["facts"][0]["evidence"][0]["text"] = "301 GeV"
            contract["reading"] = fx.write_json(rd / "inputs/reading.json", reading)
            plan["reading"] = contract["reading"]
        contract["request_plan"] = fx.write_json(rd / "inputs/plan.json", plan)
    errors = vtc.validate_pins(str(rd), contract)
    assert any(needle in e for e in errors), errors


def test_validate_pins_refuses_symlinked_records(tmp_path):
    rd = tmp_path / "run"
    contract, _, _ = fx.pinned_run(rd)
    target = tmp_path / "elsewhere.json"
    target.write_bytes((rd / "inputs/plan.json").read_bytes())
    (rd / "inputs/plan.json").unlink()
    (rd / "inputs/plan.json").symlink_to(target)
    assert any("regular file" in e for e in vtc.validate_pins(str(rd), contract))


def test_check_task_contract_reports_pins_only_when_pinned(tmp_path):
    rd = tmp_path / "run"
    contract, _, _ = fx.pinned_run(rd)
    facts = {"task_contract_path": "inputs/task_contract.json"}
    status, _, checks = validate_run_state.check_task_contract(str(rd), contract, facts, "R", False)
    assert status == "PASS" and [c["name"] for c in checks] == ["schema", "pins"]
    (rd / "inputs/plan.json").write_text("{}")
    status, _, checks = validate_run_state.check_task_contract(str(rd), contract, facts, "R", False)
    assert status == "FAIL" and checks[-1]["name"] == "pins"
    plain = fx.contract()
    status, _, checks = validate_run_state.check_task_contract(str(rd), plain, facts, "R", False)
    assert status == "PASS" and [c["name"] for c in checks] == ["schema"]


# --------------------------------------------------------------------------- #
#  approval binding
# --------------------------------------------------------------------------- #

def test_unpinned_contract_keeps_the_same_approval_path_list(tmp_path):
    rd = tmp_path / "run"
    fx.write_json(rd / "inputs/task_contract.json", fx.contract())
    assert workflow_state.approval_input_paths(str(rd)) == _legacy_approval_input_paths(str(rd))


def test_pinned_contract_appends_reading_plan_and_delegated_defaults(tmp_path):
    rd = tmp_path / "run"
    fx.pinned_run(rd)
    paths = workflow_state.approval_input_paths(str(rd))
    legacy = _legacy_approval_input_paths(str(rd))
    assert paths[:3] == legacy[:3]
    assert paths[3:] == [str(rd / "inputs/reading.json"), str(rd / "inputs/plan.json"),
                         str(rd / intake_records.DELEGATED_DEFAULTS_PATH)]


@pytest.mark.parametrize("record", ["inputs/reading.json", "inputs/plan.json", "inputs/delegated_defaults.json"])
def test_editing_a_pinned_record_after_approval_fails_verify_pair(tmp_path, record):
    rd = tmp_path / "run"
    contract, reading, plan = fx.pinned_run(rd)
    paths = workflow_state.approval_input_paths(str(rd))
    stamp = provenance.provenance_pair(workflow_state.APPROVAL_GENERATOR, paths)
    assert provenance.verify_pair(stamp, workflow_state.APPROVAL_GENERATOR, paths)[0]
    target = rd / record
    target.write_text((target.read_text() if target.exists() else "{}") + "\n")
    ok, reason = provenance.verify_pair(stamp, workflow_state.APPROVAL_GENERATOR,
                                        workflow_state.approval_input_paths(str(rd)))
    assert not ok and "fingerprint" in reason
