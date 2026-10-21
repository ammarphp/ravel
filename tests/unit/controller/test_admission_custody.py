"""Route pin identity and retained watcher inputs at installed admission consumers."""
import hashlib
import json

import pytest

import fakes
from ravel.controller import graph, routes
from ravel.controller.store import RunStore
from ravel.workflow.preflight_watcher import arm_watcher


@pytest.fixture
def store(tmp_path, monkeypatch):
    fakes.isolate(tmp_path, monkeypatch)
    return RunStore.create(tmp_path / "run", run_id="input-custody")


@pytest.mark.parametrize("fault", ["missing", "unknown", "wrong-kind", "wrong-route"])
def test_admission_requires_the_pinned_route_record(store, fault):
    route = {"id": "judgment"}
    if fault == "unknown":
        route["record_id"] = "route-not-recorded"
    elif fault == "wrong-kind":
        route["record_id"] = store.append("plan", {"route": "judgment"})
    elif fault == "wrong-route":
        route["record_id"] = store.append("route", {"route": "inspect"})
    state = {"route": route}
    before = {"work": {"attempts": 2, "status": "retry"}}
    admitted, held, holds = graph._admitted(state, store, {"steps": [{"id": "work"}]}, ["work"], before)
    assert admitted == [] and held["work"]["status"] == "held"
    assert held["work"]["attempts"] == 2 and holds["work"]["reason"] == "route_not_pinned"
    assert store.latest("admission")["record"]["code"] == "route_not_pinned"
    route["record_id"] = store.append("route", {"route": "judgment"})
    assert graph._admitted(state, store, {"steps": [{"id": "work"}]}, ["work"], before) == (["work"], {}, {})


def test_recorded_inspection_classification_precedes_scientific_task_mode():
    contract = {"task_mode": "reproduce", "intake": {"kind": "inspect"}, "prompt": "Inspect the route source."}
    reading = {"deliverables": [{"id": "D1", "artifact": {"kind": "document"}, "claim_kind": "document"}]}
    assert routes.select(contract, reading, [])["route"] == "inspect"
    reading["deliverables"][0].update(artifact={"kind": "inference"}, claim_kind="exclusion")
    # Conflicting intake records keep every scientific obligation for judgment.
    assert routes.select(contract, reading, [])["route"] == "judgment"


@pytest.mark.parametrize("fault", ["scratch", "unretained", "changed", "revoked", "symlink", "other-fire",
                                    "comment", "extra-command", "argument", "missing"])
def test_watcher_target_requires_current_input_custody(store, fault):
    root = store.run_dir
    target = root / "inputs" / "notify.sh"
    target.parent.mkdir()
    target.write_text('test -n "$5"\n')
    declaration = {"artifact": "prepare:notify.sh", "step_id": "prepare", "path": "notify.sh",
                   "destination": "inputs/notify.sh", "status": "accepted",
                   "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    store.append("custody", declaration)
    fire = f"sh {target} a b c d e"
    good, _ = arm_watcher(str(root), "notify", fire, str(target))
    assert good["verdict"] == "pass" and good["refusal_codes"] == []
    if fault in ("scratch", "unretained"):
        target = root / ("scratch" if fault == "scratch" else "inputs") / "other.sh"
        target.parent.mkdir(exist_ok=True)
        target.write_text('test -n "$5"\n')
        fire = f"sh {target} a b c d e"
    elif fault == "changed":
        target.write_text('test -n "$5"\n# altered\n')
    elif fault == "revoked":
        store.append("custody", {**declaration, "status": "rejected"})
    elif fault == "symlink":
        original = target.with_suffix(".original")
        target.rename(original)
        target.symlink_to(original)
    elif fault == "other-fire":
        fire = f"sh {root / 'scratch' / 'notify.sh'} a b c d e"
    elif fault == "comment":
        fire = f"sh {root / 'scratch' / 'notify.sh'} a b c d e # {target}"
    elif fault == "extra-command":
        fire += "; sh scratch/notify.sh a b c d e"
    elif fault == "argument":
        fire = f"sh {root / 'scratch' / 'notify.sh'} {target} a b c d e"
    else:
        target = None
    refused, relative = arm_watcher(str(root), "notify", fire, str(target) if target else None)
    assert refused["verdict"] == "fail" and refused["refusal_codes"] == ["watcher_target_not_durable"]
    assert json.loads((root / relative).read_bytes()) == refused


def test_retained_watcher_still_requires_five_arguments(store):
    target = store.run_dir / "inputs" / "notify.sh"
    target.parent.mkdir()
    target.write_text('test -n "$5"\n')
    store.append("custody", {"artifact": "prepare:notify.sh", "destination": "inputs/notify.sh",
                             "status": "accepted", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    refused, _ = arm_watcher(str(store.run_dir), "notify", f"sh {target} a b c", str(target))
    assert refused["verdict"] == "fail"
    assert any(c["name"] == "arity" and c["level"] == "FAIL" for c in refused["checks"])


def test_watcher_step_output_requires_a_retained_plan_input_declaration(store):
    target = store.run_dir / "steps" / "prepare" / "notify.sh"
    target.parent.mkdir(parents=True)
    target.write_text('test -n "$5"\n')
    artifact = "prepare:notify.sh"
    store.append("custody", {"artifact": artifact, "destination": "steps/prepare/notify.sh",
                             "status": "accepted", "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    fire = f"sh {target} a b c d e"
    refused, _ = arm_watcher(str(store.run_dir), "notify", fire, str(target))
    assert refused["refusal_codes"] == ["watcher_target_not_durable"]
    blob = store.put_blob(json.dumps({"steps": [{"inputs": [{"artifact": artifact}]}]}).encode())
    store.append("plan", {"blob": blob})
    accepted, _ = arm_watcher(str(store.run_dir), "notify", fire, str(target))
    assert accepted["verdict"] == "pass" and accepted["refusal_codes"] == []
