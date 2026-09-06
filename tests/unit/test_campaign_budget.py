import json
from pathlib import Path

import pytest

from ravel.workflow import campaign_budget as cb
from ravel.workflow.execution import digest, file_hash


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "verify_approval", lambda *a, **k: [])
    budget = {"mode": "scan", "backend": "native", "points": 4, "events_per_point": 1000}
    put(tmp_path / "inputs/cost_preflight.json", budget)
    put(tmp_path / "inputs/task_contract.json", {"cost_estimate": budget})
    put(tmp_path / "inputs/checkin1.json", {})
    put(tmp_path / "inputs/checkin1_approval.json", {})
    (tmp_path / "runs").mkdir()
    return tmp_path


def child(campaign, name="sample", n=1000):
    root = campaign / "runs" / name
    root.mkdir()
    (root / "config.toml").write_text(f"[madgraph.run]\nnevents = {n}\n")
    put(root / "inputs/native_execution_plan.json", {"nevents": n})
    return root


def attempt(root, identity="one", status="succeeded", plan=None):
    plan = plan or root / "inputs/native_execution_plan.json"
    spec = {"command": ["fake", "generate"], "cwd": str(root), "inputs": [str(plan)], "outputs": [],
            "input_snapshot": {str(plan): {"kind": "file", "files": [{"name": ".", "sha256": file_hash(plan)}]}},
            "parents": {}, "runtime": {}}
    record = {**spec, "fingerprint": digest(spec), "stage": "madgraph", "attempt_id": identity,
              "attempt_record": f"logs/execution/madgraph/{identity}/record.json", "status": status,
              "started_utc": f"2026-01-01T00:00:{len(list(root.glob('logs/execution/madgraph/*/record.json'))):02d}+00:00",
              "log": str(root / "logs/madgraph.log")}
    put(root / record["attempt_record"], record)
    put(root / "execution_state.json", {"stages": {"madgraph": record}})
    return record


def test_failed_and_running_attempts_charged_and_unstarted_child_reserved(campaign):
    root = child(campaign)
    attempt(root, "failed", "failed")
    attempt(root, "running", "running")
    child(campaign, "prepared")
    result = cb.native_campaign_budget(campaign, additional_events=1000)
    assert result["charged_or_reserved_events"] == 3000
    assert result["remaining_events_after_addition"] == 0
    assert result["runs"][0]["pending_reserved_events"] == 1000
    assert {r["status"] for r in result["runs"][1]["attempts"]} == {"failed", "running"}
    with pytest.raises(ValueError, match="exhausted"):
        cb.native_campaign_budget(campaign, additional_events=1001)


def test_bound_old_attempt_exposure_survives_current_plan_change(campaign):
    root = child(campaign)
    original = root / "inputs/native_execution_plan.json"
    attempt(root, status="failed")
    archived = root / "archive/failed/inputs/native_execution_plan.json"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(original.read_bytes())
    (root / "config.toml").write_text("[madgraph.run]\nnevents = 2000\n")
    put(original, {"nevents": 2000})
    result = cb.native_campaign_budget(campaign)
    assert result["charged_or_reserved_events"] == 3000
    assert result["runs"][0]["attempts"][0]["requested_events"] == 1000
    archived.unlink()
    with pytest.raises(ValueError, match="original generation plan bytes unavailable"):
        cb.native_campaign_budget(campaign)


def test_unknown_exposure_and_orphan_generation_never_disappear(campaign):
    root = child(campaign)
    (root / "work/madgraph/attempt-orphan").mkdir(parents=True)
    with pytest.raises(ValueError, match="unaccounted generation"):
        cb.native_campaign_budget(campaign)
    (root / "work/madgraph/attempt-orphan").rmdir()
    (root / "config.toml").write_text("[madgraph.run]\nseed = 1\n")
    with pytest.raises(ValueError, match="configured exposure"):
        cb.native_campaign_budget(campaign)


def test_mismatched_cost_and_tampered_attempt_rejected(campaign):
    root = child(campaign)
    path = root / "inputs/cost_preflight.json"
    put(path, {"backend": "native", "points": 1, "events_per_point": 900})
    with pytest.raises(ValueError, match="declarations disagree"):
        cb.native_campaign_budget(campaign)
    path.unlink()
    record = attempt(root)
    record["command"] = ["changed"]
    put(root / record["attempt_record"], record)
    with pytest.raises(ValueError, match="specification changed"):
        cb.native_campaign_budget(campaign)


def test_missing_actual_parent_approval_is_not_inferred(tmp_path):
    with pytest.raises(ValueError, match="parent approval invalid"):
        cb.native_campaign_budget(tmp_path)


def test_stale_parent_and_boolean_budget_refused(campaign, monkeypatch):
    monkeypatch.setattr(cb, "verify_approval", lambda *a, **k: ["stale binding"])
    with pytest.raises(ValueError, match="stale binding"):
        cb.native_campaign_budget(campaign)
    monkeypatch.setattr(cb, "verify_approval", lambda *a, **k: [])
    budget = {"mode": "scan", "backend": "native", "points": True, "events_per_point": 1000}
    put(campaign / "inputs/cost_preflight.json", budget)
    put(campaign / "inputs/task_contract.json", {"cost_estimate": budget})
    with pytest.raises(ValueError, match="positive integer"):
        cb.native_campaign_budget(campaign)


def test_failed_no_scratch_does_not_cover_unrelated_work_directory(campaign):
    root = child(campaign)
    attempt(root, status="failed")
    assert cb.native_campaign_budget(campaign)["charged_or_reserved_events"] == 1000
    (root / "work/madgraph/attempt-unrecorded").mkdir(parents=True)
    with pytest.raises(ValueError, match="unaccounted generation"):
        cb.native_campaign_budget(campaign)


def test_current_and_archived_logs_bind_each_scratch_to_original_attempt(campaign):
    root = child(campaign)
    attempt(root, "old", "failed")
    latest = attempt(root, "new", "running")
    first, second = [root / "work/madgraph" / name for name in ("attempt-first", "attempt-second")]
    first.mkdir(parents=True)
    second.mkdir()
    (root / "logs/madgraph.log").write_text(f"MadGraph working directory: {second}\n")
    prior = root / Path(latest["attempt_record"]).parent / "prior.log"
    prior.write_text(f"MadGraph working directory: {first}\n")
    result = cb.native_campaign_budget(campaign)
    assert result["charged_or_reserved_events"] == 2000
    assert {a["work_directory"] for a in result["runs"][0]["attempts"]} == {str(first), str(second)}
    prior.write_text(f"MadGraph working directory: {second}\n")
    with pytest.raises(ValueError, match="claimed by multiple"):
        cb.native_campaign_budget(campaign)


def test_boolean_child_point_count_is_not_one(campaign):
    root = child(campaign)
    put(root / "inputs/cost_preflight.json", {"backend": "native", "points": True, "events_per_point": 1000})
    with pytest.raises(ValueError, match="positive integer"):
        cb.native_campaign_budget(campaign)


def test_archived_generation_work_requires_explicit_root_mapping(campaign):
    root = child(campaign)
    (root / "archive/old/work/madgraph/attempt-orphan").mkdir(parents=True)
    with pytest.raises(ValueError, match="unsupported archived root"):
        cb.native_campaign_budget(campaign)


def register_policy(campaign, effective=3000, basis=None):
    basis = basis or cb.native_campaign_budget(campaign)
    basis_path = campaign / 'inputs/budget-policies/inventory.json'
    put(basis_path, basis)
    policy = {'schema_version': 1, 'policy_id': 'resource-restriction-v1',
              'original_allocation_events': 4000, 'effective_allocation_events': effective,
              'parent_bindings': {'inputs/' + name: file_hash(campaign / 'inputs' / name) for name in cb.PARENT_INPUTS},
              'inventory_basis': {'path': basis_path.relative_to(campaign).as_posix(), 'sha256': file_hash(basis_path)},
              'reason': 'Reduce unused optional exposure to preserve storage floor.',
              'scope': 'Same nominal population and criteria; one fewer optional control.'}
    policy_path = campaign / 'inputs/budget-policies/ceiling.json'
    put(policy_path, policy)
    put(campaign / cb.POLICY_REGISTRATION, {'schema_version': 1, 'path': policy_path.relative_to(campaign).as_posix(), 'sha256': file_hash(policy_path)})
    return file_hash(policy_path), policy_path


def test_registered_ceiling_is_automatic_and_required_pin_is_exact(campaign):
    child(campaign)
    expected, _ = register_policy(campaign)
    result = cb.native_campaign_budget(campaign, additional_events=2000, required_policy_sha256=expected)
    assert result['parent_allocation_events'] == 4000
    assert result['effective_allocation_events'] == 3000
    assert result['remaining_events_after_addition'] == 0
    assert result['budget_policy']['sha256'] == expected
    with pytest.raises(ValueError, match='exhausted'):
        cb.native_campaign_budget(campaign, additional_events=2001)
    with pytest.raises(ValueError, match='required policy SHA'):
        cb.native_campaign_budget(campaign, required_policy_sha256='0' * 64)


def test_policy_basis_permits_progress_and_additions_without_losing_old_attempts(campaign):
    root = child(campaign)
    attempt(root, 'failed', 'failed')
    expected, _ = register_policy(campaign)
    attempt(root, 'second', 'running')
    child(campaign, 'new')
    result = cb.native_campaign_budget(campaign, required_policy_sha256=expected)
    assert result['charged_or_reserved_events'] == 3000
    assert result['remaining_events_after_addition'] == 0
    (root / 'logs/execution/madgraph/failed/record.json').unlink()
    with pytest.raises(ValueError, match='historical generation attempt charge changed'):
        cb.native_campaign_budget(campaign)


def test_policy_reserved_child_can_start_but_cannot_disappear(campaign):
    root = child(campaign)
    expected, _ = register_policy(campaign)
    attempt(root)
    assert cb.native_campaign_budget(campaign, required_policy_sha256=expected)['charged_or_reserved_events'] == 1000
    root.rename(campaign / 'relocated')
    with pytest.raises(ValueError, match='historical campaign charge disappeared'):
        cb.native_campaign_budget(campaign)


@pytest.mark.parametrize('missing', ['registration', 'policy', 'basis', 'all'])
def test_missing_policy_layers_fail_closed_when_pinned(campaign, missing):
    expected, policy = register_policy(campaign)
    if missing in ('registration', 'all'):
        (campaign / cb.POLICY_REGISTRATION).unlink()
    if missing in ('policy', 'all'):
        policy.unlink()
    if missing in ('basis', 'all'):
        (campaign / 'inputs/budget-policies/inventory.json').unlink()
    with pytest.raises(ValueError, match='missing'):
        cb.native_campaign_budget(campaign, required_policy_sha256=expected)
    if missing == 'registration':
        with pytest.raises(ValueError, match='registration is missing'):
            cb.native_campaign_budget(campaign)


@pytest.mark.parametrize('value', [True, 0, -1, 3000.0, 4000, 5000])
def test_ceiling_must_be_exact_positive_integer_strictly_below_parent(campaign, value):
    register_policy(campaign, effective=value)
    with pytest.raises(ValueError, match='positive integer|strictly lower'):
        cb.native_campaign_budget(campaign)


def test_policy_bytes_and_bound_parent_are_not_reinterpreted(campaign):
    _, policy_path = register_policy(campaign)
    value = json.loads(policy_path.read_text())
    value['reason'] = 'Edited after registration'
    put(policy_path, value)
    with pytest.raises(ValueError, match='artifact changed'):
        cb.native_campaign_budget(campaign)
    registration = json.loads((campaign / cb.POLICY_REGISTRATION).read_text())
    registration['sha256'] = file_hash(policy_path)
    put(campaign / cb.POLICY_REGISTRATION, registration)
    put(campaign / 'inputs/checkin1.json', {'new': 'later parent approval inputs'})
    with pytest.raises(ValueError, match='parent approval binding changed'):
        cb.native_campaign_budget(campaign)


@pytest.mark.parametrize('relative', ['../outside.json', '/tmp/outside.json', 'inputs/budget-policies/../outside.json', 'inputs/budget-policies//ceiling.json'])
def test_policy_reference_cannot_escape_or_alias_canonical_directory(campaign, relative):
    register_policy(campaign)
    registration = json.loads((campaign / cb.POLICY_REGISTRATION).read_text())
    registration['path'] = relative
    put(campaign / cb.POLICY_REGISTRATION, registration)
    with pytest.raises(ValueError, match='path/hash is invalid'):
        cb.native_campaign_budget(campaign)


def test_registered_policy_symlink_rejected(campaign):
    _, policy = register_policy(campaign)
    outside = campaign / 'outside.json'
    policy.rename(outside)
    policy.symlink_to(outside)
    with pytest.raises(ValueError, match='symlinked'):
        cb.native_campaign_budget(campaign)


def test_policy_inventory_total_cannot_hide_missing_charge(campaign):
    child(campaign)
    basis = cb.native_campaign_budget(campaign)
    basis['charged_or_reserved_events'] = 0
    register_policy(campaign, basis=basis)
    with pytest.raises(ValueError, match='basis total contradicts'):
        cb.native_campaign_budget(campaign)
