"""P12: legacy layouts are inspectable and refused for new science (L01, SW26)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ravel.controller.routes import legacy


def owner_of(*owned):
    """A fake ``controller_owned``: the run id for these directories (and their contents), else None."""
    table = {os.path.realpath(path): run_id for path, run_id in owned}

    def owner(run_dir):
        real = os.path.realpath(run_dir)
        for path, run_id in table.items():
            if real == path or real.startswith(path + os.sep):
                return run_id
        return None
    return owner


def contract(epoch=None, task_mode="reproduce"):
    value = {"task_mode": task_mode}
    if epoch is not None:
        value["agent_layer_epoch"] = epoch
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))


def epoch_one(tmp_path):
    run = tmp_path / "old-run"
    write(run / "task_contract.json", contract())
    (run / "request.txt").write_text("an earlier request\n", encoding="utf-8")
    return run


def epoch_two(tmp_path):
    run = tmp_path / "v1-run"
    write(run / "inputs" / "task_contract.json", contract(epoch=2))
    return run


def test_L01_epoch_one_layout_refused_for_new_science(tmp_path):
    run = epoch_one(tmp_path)
    view = legacy.check(run, owner=owner_of())
    assert view["layout"] == "epoch-one" and view["legacy"] is True
    assert view["new_science"] is False and view["inspectable"] is True
    assert view["governance"] == legacy.NOT_GOVERNED
    assert {r["code"] for r in view["reasons"]} >= {"epoch_one_layout", "legacy_inspection_only"}
    refusal = legacy.admit_new_run(run, owner=owner_of())
    assert refusal and "new science is refused" in refusal
    # Inspection works and writes nothing.
    before = snapshot(run)
    described = legacy.inspect(run, owner=owner_of())
    assert described["label"] == legacy.NOT_GOVERNED
    assert described["layout"]["evidence"]["contract"] == "task_contract.json"
    assert described["layout"]["evidence"]["contract_sha256"]
    assert {e["name"] for e in described["entries"]} == {"task_contract.json", "request.txt"}
    assert snapshot(run) == before


def test_L01_one_x_run_is_legacy_but_inspectable(tmp_path):
    run = epoch_two(tmp_path)
    view = legacy.check(run, owner=owner_of())
    assert view["layout"] == "epoch-two" and view["legacy"] and not view["new_science"]
    assert legacy.admit_new_run(run, owner=owner_of())
    assert legacy.resume_errors(run, "r-1", owner=owner_of())


def test_L01_inputs_contract_without_epoch_two_is_epoch_one(tmp_path):
    run = tmp_path / "run"
    write(run / "inputs" / "task_contract.json", contract())
    assert legacy.check(run, owner=owner_of())["layout"] == "epoch-one"


def test_L01_run_root_contract_cannot_claim_a_later_epoch(tmp_path):
    run = tmp_path / "run"
    write(run / "task_contract.json", contract(epoch=2))
    view = legacy.check(run, owner=owner_of())
    assert view["layout"] == "epoch-one"
    assert "later epoch" in view["reasons"][0]["message"]


def test_L01_new_directory_admitted_and_existing_directories_never_adopted(tmp_path):
    assert legacy.admit_new_run(tmp_path / "fresh", owner=owner_of()) is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert legacy.check(empty, owner=owner_of())["layout"] == "empty"
    assert legacy.admit_new_run(empty, owner=owner_of())
    other = tmp_path / "other"
    (other / "inputs").mkdir(parents=True)
    view = legacy.check(other, owner=owner_of())
    assert view["layout"] == "unrecognised" and not view["new_science"]
    assert legacy.admit_new_run(other, owner=owner_of())


def test_L01_controller_run_is_resumed_not_restarted(tmp_path):
    run = tmp_path / "governed"
    write(run / "inputs" / "task_contract.json", contract(epoch=2))
    owner = owner_of((run, "r-7"))
    view = legacy.check(run, owner=owner)
    assert view["layout"] == "controller" and view["new_science"] and not view["legacy"]
    assert view["governance"] == "controller"
    assert "ravel drive --resume r-7" in legacy.admit_new_run(run, owner=owner)
    assert legacy.resume_errors(run, "r-7", owner=owner) == []
    assert legacy.resume_errors(run, "r-8", owner=owner)


def test_SW26_run_root_contract_downgrades_a_controller_run(tmp_path):
    run = tmp_path / "governed"
    write(run / "inputs" / "task_contract.json", contract(epoch=2))
    owner = owner_of((run, "r-7"))
    assert legacy.governed_errors(run, "r-7", owner=owner) == []
    # The mutation: an epoch-one layout created inside a controller-owned run for new work.
    (run / "inputs" / "task_contract.json").unlink()
    write(run / "task_contract.json", contract())
    view = legacy.check(run, owner=owner)
    assert view["layout"] == "controller-downgraded" and not view["new_science"] and view["legacy"]
    assert {"run_root_contract", "inputs_contract_missing"} <= {r["code"] for r in view["reasons"]}
    errors = legacy.resume_errors(run, "r-7", owner=owner)
    assert errors and "SW26" in errors[0]
    assert legacy.governed_errors(run, "r-7", owner=owner) == errors
    assert legacy.admit_new_run(run, owner=owner)
    assert view["inspectable"]


@pytest.mark.parametrize("mutation", ["root-copy", "epoch-one-inputs", "unreadable", "symlink"])
def test_SW26_every_epoch_downgrade_of_a_controller_run_is_refused(tmp_path, mutation):
    run = tmp_path / "governed"
    write(run / "inputs" / "task_contract.json", contract(epoch=2))
    owner = owner_of((run, "r-7"))
    target = run / "inputs" / "task_contract.json"
    if mutation == "root-copy":
        write(run / "task_contract.json", contract(epoch=2))
    elif mutation == "epoch-one-inputs":
        write(target, contract(epoch=1))
    elif mutation == "unreadable":
        target.write_text("{not json", encoding="utf-8")
    else:
        outside = tmp_path / "elsewhere.json"
        write(outside, contract(epoch=2))
        target.unlink()
        target.symlink_to(outside)
    assert legacy.check(run, owner=owner)["layout"] == "controller-downgraded"
    assert legacy.resume_errors(run, "r-7", owner=owner)


def test_SW26_positive_control_intact_controller_run_passes(tmp_path):
    run = tmp_path / "governed"
    write(run / "inputs" / "task_contract.json", contract(epoch=2))
    (run / "steps").mkdir()
    assert legacy.check(run, owner=owner_of((run, "r-7")))["layout"] == "controller"


def test_L01_ownership_failure_never_reads_as_legacy_or_new(tmp_path):
    run = epoch_two(tmp_path)

    def broken(run_dir):
        raise OSError("store unreadable")
    view = legacy.check(run, owner=broken)
    assert view["layout"] == "unrecognised" and not view["new_science"] and not view["legacy"]
    assert legacy.admit_new_run(run, owner=broken)


def test_L01_supplied_runs_are_reclassified_and_labelled(tmp_path):
    old, governed = epoch_one(tmp_path), tmp_path / "governed"
    write(governed / "inputs" / "task_contract.json", contract(epoch=2))
    data = tmp_path / "events.lhe"
    data.write_text("<LesHouchesEvents>\n", encoding="utf-8")
    supplied = [{"kind": "directory", "path": str(old)}, {"kind": "directory", "path": str(governed)},
                {"kind": "events", "path": str(data)}]
    rows = legacy.classify_supplied(supplied, owner=owner_of((governed, "r-7")))
    assert rows[0]["kind"] == "legacy-run" and rows[0]["governance"] == legacy.NOT_GOVERNED
    assert rows[1]["kind"] == "controller-run" and rows[1]["controller_run"] == "r-7"
    assert rows[2] == supplied[2]
    assert supplied[0]["kind"] == "directory"  # the input rows are copied, never changed


def test_L01_decision_gate_keeps_epoch_one_decisions_for_legacy_commands(tmp_path):
    """The legacy command path is unchanged: an epoch-one run still gets its epoch-one decision."""
    from ravel.workflow import decision_gate
    run = epoch_one(tmp_path)
    assert decision_gate._facts(Path(run)) == {"agent_layer_epoch": 1}


# ---- the hooks through the controller entry and graph (P01) --------------------------------------

@pytest.fixture
def controller(tmp_path, monkeypatch):
    """Controller runs with the interface fakes, their store under the test's temporary directory."""
    import fakes
    from ravel.controller import store as store_module
    from ravel.workflow import agent_tripwire
    fakes.isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(store_module, "_operator_config", lambda: {})
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])  # a controller declaration lasts for its process
    with fakes.stand_in_graphs():
        yield tmp_path


def _minimal_layout(monkeypatch):
    """No request plan can be drafted: the intake writes the controller's minimal layout."""
    from ravel import cli

    def no_plan(reading, contract):
        raise ValueError("no request plan can be drafted (fixture)")
    monkeypatch.setattr(cli, "_draft_plan", no_plan)


def _dispatched():
    import fakes
    return [step for step, _ in fakes.DISPATCHED]


def test_SW26_minimal_layout_run_resumes_as_governed(controller, monkeypatch):
    import fakes
    from ravel.controller import entry
    _minimal_layout(monkeypatch)
    with fakes.installed(authority=fakes.FakeAuthority({"approve_plan": ["pending", "approve"]})):
        store, observation = fakes.drive_request(controller)
        assert [i["payload"]["authority_kind"] for i in observation["interrupts"]] == ["approve_plan"]
        assert store.latest("intake")["record"]["layout"] == "minimal"
        view = legacy.check(store.run_dir)
        assert view["layout"] == "controller" and view["evidence"]["agent_layer_epoch"] == 2, view["reasons"]
        assert legacy.resume_errors(store.run_dir, store.run_id) == []
        resumed = entry.open_for_resume(store.run_id, root=controller / "controller-store")
        observation = entry.drive(resumed, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    assert observation["terminal"] is None and "j1" in _dispatched()
    contract = json.loads((store.run_dir / "inputs" / "task_contract.json").read_text())
    assert contract["agent_layer_epoch"] == 2 and not (store.run_dir / "task_contract.json").exists()


def test_SW26_a_controller_run_downgraded_outside_the_controller_is_not_resumed(controller, capsys):
    import fakes
    from ravel import cli
    from ravel.controller import entry
    with fakes.installed(authority=fakes.FakeAuthority({"approve_plan": "pending"})):
        store, _ = fakes.drive_request(controller)
    assert entry.open_for_resume(store.run_id, root=controller / "controller-store")  # positive control
    write(store.run_dir / "task_contract.json", contract())  # an epoch-one layout written from outside
    with pytest.raises(entry.EntryError, match="SW26"):
        entry.open_for_resume(store.run_id, root=controller / "controller-store")


def test_SW26_a_downgrade_mid_run_holds_the_next_wave(controller, monkeypatch):
    import fakes
    plan = fakes.judgment_plan(steps=[fakes.make_step("j1", kind="derive", outputs=["outputs/a.json"]),
                                      fakes.make_step("j2", kind="derive", depends_on=["j1"],
                                                      outputs=["outputs/b.json"])])
    fakes.PLANS.append(plan)
    real_step = fakes.step_run

    def downgrading(store, step, context):
        if step["id"] == "j1":  # while the run executes, an epoch-one contract appears at its root
            write(Path(context["run_dir"]) / "task_contract.json", contract())
        return real_step(store, step, context)
    monkeypatch.setattr(fakes, "step_run", downgrading)
    with fakes.installed() as svc:
        store, observation = fakes.drive_request(controller)
    assert "j1" in _dispatched() and "j2" not in _dispatched()
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    failures = fakes.final_state(store)["failures"].values()
    assert any("legacy_layout" in json.dumps(f) for f in failures)


def test_L01_read_only_selection_refuses_an_effectful_plan_revision(controller):
    import fakes
    from ravel.controller import graph
    from ravel.controller.store import RunStore
    store = RunStore.create(controller / "runs" / "inspected", root=controller / "controller-store")
    store.append("route", {"route": "inspect", "row": 9, "spec_sha256": None, "version": 1, "evidence_blob": None})
    effectful = fakes.judgment_plan(steps=[fakes.make_step("j1", kind="operate", outputs=["outputs/x.json"])])
    with pytest.raises(graph.nodes.RecoveryHold) as refused:
        graph._install_plan(store, effectful, source="judgment", revision=1)
    assert refused.value.reason == "plan_invalid" and "effectful_kind" in refused.value.would_make_possible
    assert store.scan("plan") == []
    reading = fakes.judgment_plan(steps=[fakes.make_step("j1", kind="synthesize", outputs=[])])
    reading["steps"][0]["outputs"] = [{"path": "outputs/answer.md", "kind": "document", "required": True}]
    from ravel.controller.routes import plan_sha256
    reading["sha256"] = plan_sha256(reading)
    assert graph._install_plan(store, reading, source="judgment", revision=1)["record_id"]  # positive control


def test_L01_an_alias_of_a_legacy_run_is_the_legacy_run(tmp_path):
    run = epoch_one(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(run, target_is_directory=True)
    view = legacy.check(alias, owner=owner_of())
    assert view["layout"] == "epoch-one" and view["evidence"]["alias_of"] == os.path.realpath(run)
    assert legacy.admit_new_run(alias, owner=owner_of())
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "missing")
    view = legacy.check(dangling, owner=owner_of())
    assert view["layout"] == "unrecognised" and not view["new_science"]
    assert legacy.admit_new_run(dangling, owner=owner_of())
