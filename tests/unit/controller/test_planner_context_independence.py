"""A revised planner receives only the inputs its governed step declares."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from ravel.controller import step as governed_step
from ravel.controller.judgment import services as judgment_services
from ravel.controller.step import binding, spec
from ravel.workflow import agent_worker

import test_p08_fakes as judgment_fakes
from test_p04_support import (context, graphs, inert_worker, run_env,  # noqa: F401
                              services_installed)
from test_p08_fakes import Fixture, invoke, judgment_graph, plan, step


def test_second_decomposition_materializes_only_its_declared_context(
        tmp_path, monkeypatch, run_env, inert_worker, graphs):
    # Both packages must address the same run and blob store, including the
    # immutable request pins that the judgment graph copies into run inputs.
    monkeypatch.setattr(judgment_fakes, "RUN_ID", run_env.store.run_id)
    fixture_root = tmp_path / "judgment"
    fixture_root.mkdir()
    fixture = Fixture(fixture_root)
    for pin in ("sha256", "reading_sha256", "contract_sha256"):
        raw = fixture.store.get_blob(fixture.pins[pin])
        assert run_env.store.put_blob(raw) == fixture.pins[pin]
    fixture.store = run_env.store
    fixture.run_dir = run_env.run_dir
    assert fixture.view()["context"]["run_id"] == fixture.store.run_id

    # An undeclared step-scoped controller context (as an earlier round leaves): never another round's input.
    sentinel_path = "inputs/judgment/unrelated-context.json"
    sentinel = {"context_sentinel": "unrelated input must stay outside this seat"}
    (run_env.run_dir / sentinel_path).parent.mkdir(parents=True, exist_ok=True)
    (run_env.run_dir / sentinel_path).write_text(json.dumps(sentinel))
    frame_doc = fixture.frame_doc()
    invalid_plan = plan(frame_doc, [step("compute", kind="freeform")])
    valid_plan = plan(frame_doc, [step("compute")])
    dispatched = []

    def run_planning_step(store, row, judgment_context):
        # Review credit uses the existing interface fake; planning authors run
        # through the real governed step and materialize their actual inputs.
        if row["kind"] == "review":
            return fixture.steps(store, row, judgment_context)
        document = None
        if row["id"].startswith("judgment-frame-") and row["kind"] == "author":
            document = frame_doc
        elif row["id"].startswith("judgment-decompose-"):
            document = invalid_plan if row["id"] == "judgment-decompose-r0-1" else valid_plan
        if document is None:
            inert_worker.scenario()
        else:
            inert_worker.scenario(writes=[{
                "path": row["outputs"][0]["path"],
                "content": json.dumps(document, sort_keys=True),
            }])
        step_context = context(store, run_env.run_dir, judgment_context["plan_sha256"],
                               **{key: value for key, value in judgment_context.items()
                                  if key not in {"plan_sha256", "run_dir"}})
        outcome = governed_step.run(store, row, step_context)
        if outcome["status"] != "completed":
            print(json.dumps({"step": row["id"], "outcome": outcome}, indent=2))
        assert outcome["status"] == "completed", outcome
        dispatched.append((deepcopy(row), outcome))
        return outcome

    def bind_plan(store, document, **options):
        return binding.record_plan_rows(store, document, ledger=run_env.fakes["ledger"], **options)

    preferences = context(fixture.store, fixture.run_dir, "unused")["agent_preferences"]
    with judgment_graph(), fixture.installed(), judgment_services.overridden(
            step_run=run_planning_step, plan_bind=bind_plan):
        result = invoke(fixture, fixture.view(agent_preferences=preferences))

    if result["outcome"] != "ok":
        print(json.dumps(result, indent=2))
        for path in fixture_root.rglob("*.jsonl"):
            if "traceback" in path.read_text():
                print(path.read_text()[-12000:])
    assert result["outcome"] == "ok", result
    events = fixture.events("plan")
    assert [event["status"] for event in events] == ["refused", "written"]
    assert any("freeform" in problem for problem in events[0]["problems"])
    decompositions = [row for row, _ in dispatched if row["id"].startswith("judgment-decompose-")]
    assert [row["id"] for row in decompositions] == ["judgment-decompose-r0-1", "judgment-decompose-r0-2"]
    first, second = decompositions
    first_context = next(pin for pin in first["inputs"] if "/decompose-r0-1-" in pin["artifact"])
    second_context = next(pin for pin in second["inputs"] if "/decompose-r0-2-" in pin["artifact"])
    assert first_context["artifact"] not in {pin["artifact"] for pin in second["inputs"]}
    assert sentinel_path not in {pin["artifact"] for pin in second["inputs"]}
    first_raw = (run_env.run_dir / first_context["artifact"]).read_bytes()
    assert hashlib.sha256(first_raw).hexdigest() == first_context["sha256"]
    second_raw = (run_env.run_dir / second_context["artifact"]).read_bytes()
    assert hashlib.sha256(second_raw).hexdigest() == second_context["sha256"]
    expected_context = json.loads(second_raw)
    assert expected_context["feedback"] == events[0]["problems"]
    assert expected_context["feedback"]

    workspace = agent_worker.workspace(run_env.run_dir, spec.worker_node(second["id"]), 1)
    input_root = workspace / "inputs"
    materialized = [(path, path.read_bytes()) for path in input_root.rglob("*") if path.is_file()]
    contexts = []
    for path, raw in materialized:
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(document, dict) and document.get("schema") == "judgment-plan.v1":
            contexts.append((path, raw, document))
    assert len(contexts) == 1, [path.relative_to(input_root).as_posix() for path, _, _ in contexts]
    _, actual_raw, actual_context = contexts[0]
    assert hashlib.sha256(actual_raw).hexdigest() == second_context["sha256"]
    assert actual_context == expected_context
    assert all(raw != first_raw for _, raw in materialized)
    assert all(b"unrelated input must stay outside this seat" not in raw for _, raw in materialized)

    manifest = json.loads((input_root / "packet" / "manifest.json").read_bytes())
    declared = {pin["artifact"] for pin in second["inputs"]}
    contexts_seen = {entry["source_path"] for entry in manifest["artifacts"]
                     if entry["source_path"].startswith("inputs/judgment/")}
    assert contexts_seen == {name for name in declared if name.startswith("inputs/judgment/")}
    assert {row["source_path"]: row["source_sha256"] for row in manifest["subjects"]} == {
        pin["artifact"]: pin["sha256"] for pin in second["inputs"]}
    assert (run_env.run_dir / first_context["artifact"]).read_bytes() == first_raw
