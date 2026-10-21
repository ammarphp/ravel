"""An analysis request that names no published analysis and supplies its own analysis script.

Three joins of the analysis route for such a request:

- CHECK-IN 1 shows the resource census the controller writes for a reading that names no analysis
  (its own ``reading/targets`` rung, no record), instead of an empty census section;
- a prepared launch may read a supplied run input only as a declared input of its step, pinned to the
  bytes intake staged, so custody refuses a launch whose approved input changed;
- the data acquisition of a request without a published record writes a typed not-applicable record
  (nothing fetched) only when the run's census found no analysis and the route analysis names no
  record; the step evidence accepts it only with that evidence.

Fictional request and model; nothing calls a model, a provider, the network or a native tool.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller.routes import analysis
from ravel.controller.routes.analysis import checkins, evidence, execution
from ravel.workflow import acquisition_http, resource_census, restriction_guard
from p09_support import (Store, adopt, compile_plan, context, contract, evidence_set, reading,
                              record_outcome)

NO_TARGET = {"schema_version": 1, "records": [], "targets": {"analyses": [], "keywords": []},
             "rungs": {"reading/targets": {"status": "ABSENT",
                                           "reason": "the pinned reading names no analysis identifier; no public "
                                                     "source was consulted"}}}


def _prepared(tmp_path, census):
    store = Store()
    read, con = reading(), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    rows = evidence_set()
    rows["inputs.census"]["outputs/inputs/resource_census.json"] = census
    by_id = {s["id"]: s for s in plan["steps"]}
    states = {}
    for step_id, outputs in rows.items():
        for path, document in outputs.items():
            adopt(store, tmp_path, step_id, path, document)
        record_outcome(store, by_id[step_id])
        states[step_id] = {"status": "completed", "attempts": 1, "receipts": [f"receipt-{step_id}"]}
    plan = analysis.bind(plan, context(store, tmp_path, plan, read, con, states)) or plan
    return store, plan, read, con, states


def test_checkin1_shows_the_census_of_a_reading_that_names_no_analysis(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path, NO_TARGET)
    view = checkins.approve_plan(context(store, tmp_path, plan, read, con, states))
    assert view["errors"] == []
    census, = [s for s in view["sections"] if s["id"] == "resource_census"]
    assert census["lines"] == ["census: reading/targets: ABSENT"]


def test_census_evidence_checks_the_census_rungs_beside_its_records(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path, {**NO_TARGET, "rungs": {"reading/targets": {}}})
    step = next(s for s in plan["steps"] if s["id"] == "inputs.census")
    errors = evidence.check(step, {"status": "completed"}, context(store, tmp_path, plan, read, con, states))
    assert "census_rung_unstated" in {e["code"] for e in errors}


SUPPLIED = [{"name": "analysis.py", "artifact": "inputs/analysis.py", "sha256": "a" * 64,
             "source": "/operator/analysis.py"}]


def test_prepared_execution_effects_bind_exact_launch_and_supplied_input():
    source = {'launches': {'recast.smoke': {'argv': ['python', '@input:inputs/analysis.py']}},
              'launch_inputs': {'recast.smoke': ['inputs/analysis.py']},
              'launch_effects': {'recast.smoke': ['executes_native']}}
    bound = execution.bind_launches(_launch_plan(), source, SUPPLIED)
    node = next(row for row in bound['steps'] if row['id'] == 'recast.smoke')
    assert node['parameters']['execution_effects'] == ['executes_native']
    evidence_ = node['parameters']['execution_effects_evidence']
    assert evidence_['source_sha256'] == analysis.common.digest(source)
    assert evidence_['launch_sha256'] == analysis.common.digest(source['launches']['recast.smoke'])
    assert any(row.get('sha256') == 'a' * 64 for row in evidence_['inputs'])
    # Supplying bytes alone never asserts that a generator has stopped generating.
    source.pop('launch_effects')
    unclassified = execution.bind_launches(_launch_plan(), source, SUPPLIED)
    node = next(row for row in unclassified['steps'] if row['id'] == 'recast.smoke')
    assert 'execution_effects' not in node['parameters']


@pytest.mark.parametrize('effects', [
    {'not-a-step': []}, {'recast.smoke': ['unregistered-effect']},
    {'recast.smoke': ['executes_native', 'executes_native']}, {'recast.smoke': 'executes_native'},
])
def test_effect_claims_cannot_escape_the_prepared_operation(effects):
    with pytest.raises(ValueError, match='effects'):
        execution.bind_launches(_launch_plan(), {
            'launches': {'recast.smoke': {'argv': ['python', 'compute']}}, 'launch_effects': effects})


def _launch_plan():
    read, con = reading(), contract("reproduce")
    return compile_plan("analysis", read, con)


def test_a_prepared_launch_reads_a_staged_supplied_input_as_a_pinned_declared_input():
    plan = _launch_plan()
    source = {"launches": {"recast.smoke": {"argv": ["python", "@input:inputs/analysis.py", "smoke"]}},
              "launch_inputs": {"recast.smoke": ["inputs/analysis.py"]}}
    bound = execution.bind_launches(plan, source, SUPPLIED)
    smoke = next(s for s in bound["steps"] if s["id"] == "recast.smoke")
    row, = [r for r in smoke["inputs"] if r["artifact"] == "inputs/analysis.py"]
    assert row["sha256"] == "a" * 64 and row["required"] is True
    assert smoke["parameters"]["launch"]["argv"][1] == "@input:inputs/analysis.py"
    assert bound["sha256"] != plan["sha256"]
    untouched = next(s for s in bound["steps"] if s["id"] == "env")
    assert all(r["artifact"] != "inputs/analysis.py" for r in untouched["inputs"])


@pytest.mark.parametrize("source,message", [
    ({"launches": {"recast.smoke": {"argv": ["python", "x"]}}, "launch_inputs": {"recast.smoke": ["inputs/other.py"]}},
     "not a staged supplied input"),
    ({"launches": {}, "launch_inputs": {"recast.smoke": ["inputs/analysis.py"]}}, "without a prepared launch"),
    ({"launches": {"recast.smoke": {"argv": ["python", "x"]}}, "launch_inputs": {"recast.smoke": "inputs/analysis.py"}},
     "list of run-input artifacts"),
    ({"launches": {"recast.smoke": {"argv": ["python", "x"]}}, "launch_inputs": ["recast.smoke"]}, "keyed by exact"),
])
def test_launch_inputs_name_only_staged_supplied_inputs_of_prepared_launches(source, message):
    with pytest.raises(ValueError, match=message):
        execution.bind_launches(_launch_plan(), source, SUPPLIED)


def test_bind_reads_the_staged_rows_from_the_intake_record(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path, NO_TARGET)
    intake = store.append("intake", {"supplied": SUPPLIED})
    route = {**evidence_set()["inputs.route"]["outputs/route_analysis.json"],
             "launches": {"recast.smoke": {"argv": ["python", "@input:inputs/analysis.py"]}},
             "launch_inputs": {"recast.smoke": ["inputs/analysis.py"]}}
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route)
    ctx = context(store, tmp_path, plan, read, con, states)
    ctx["state"]["request"] = {"intake_record_id": intake}
    bound = analysis.bind(plan, ctx)
    smoke = next(s for s in bound["steps"] if s["id"] == "recast.smoke")
    assert {"artifact": "inputs/analysis.py", "sha256": "a" * 64, "kind": "supplied", "required": True} \
        in smoke["inputs"]


@pytest.mark.parametrize("existing", [
    {"artifact": "inputs/analysis.py"},
    {"artifact": "inputs/analysis.py", "sha256": None},
    {"artifact": "inputs/analysis.py", "sha256": "b" * 64},
])
def test_launch_inputs_refuse_an_existing_input_without_the_staged_pin(existing):
    plan = _launch_plan()
    smoke = next(s for s in plan["steps"] if s["id"] == "recast.smoke")
    smoke["inputs"].append(existing)
    source = {"launches": {"recast.smoke": {"argv": ["python", "@input:inputs/analysis.py"]}},
              "launch_inputs": {"recast.smoke": ["inputs/analysis.py"]}}
    with pytest.raises(ValueError, match="must match its staged supplied digest"):
        execution.bind_launches(plan, source, SUPPLIED)


def test_launch_inputs_rebind_idempotently_with_the_exact_staged_pin():
    source = {"launches": {"recast.smoke": {"argv": ["python", "@input:inputs/analysis.py"]}},
              "launch_inputs": {"recast.smoke": ["inputs/analysis.py"]}}
    bound = execution.bind_launches(_launch_plan(), source, SUPPLIED)
    rebound = execution.bind_launches(bound, source, SUPPLIED)
    assert rebound == bound
    smoke = next(s for s in rebound["steps"] if s["id"] == "recast.smoke")
    row, = [r for r in smoke["inputs"] if r["artifact"] == "inputs/analysis.py"]
    assert row["sha256"] == SUPPLIED[0]["sha256"]


def test_custody_refuses_a_launch_whose_pinned_supplied_input_changed(tmp_path):
    from ravel.controller.step import custody
    store = Store()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "analysis.py").write_text("print('approved')\n")
    approved = hashlib.sha256(b"print('approved')\n").hexdigest()
    step = {"id": "recast.smoke", "depends_on": [], "inputs": [{"artifact": "inputs/analysis.py", "sha256": approved,
                                                                 "kind": "supplied", "required": True}]}
    errors, _, supplied = custody.input_errors(store, step, tmp_path)
    assert errors == [] and supplied[0]["sha256"] == approved
    (tmp_path / "inputs" / "analysis.py").write_text("print('changed')\n")
    errors, _, _ = custody.input_errors(store, step, tmp_path)
    assert errors == [{"code": "run_input_changed", "artifact": "inputs/analysis.py"}]


# ---- the acquisition of a request without a published record -------------------------------------

@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    monkeypatch.setattr(restriction_guard, "require", lambda *a, **k: None)

    @contextmanager
    def scope(*args):
        yield {"requests": [], "bytes": 0}
    monkeypatch.setattr(acquisition_http, "scope", scope)
    fetched = []

    def fetch(args):
        fetched.append(args)
        Path(args[4]).mkdir(parents=True, exist_ok=True)
        (Path(args[4]) / "hepdata_manifest.json").write_text(json.dumps({"table_files": []}))
        return 0
    monkeypatch.setattr(resource_census, "main", fetch)

    def run(route, census):
        files = {}
        for artifact, document in (("inputs.route:outputs/route_analysis.json", route),
                                   ("inputs.census:outputs/inputs/resource_census.json", census)):
            step_id, path = artifact.split(":", 1)
            target = tmp_path / "steps" / step_id / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(document))
            files[artifact] = {"artifact": artifact, "path": f"steps/{step_id}/{path}",
                               "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        step = {"id": "acquire.data", "kind": "acquire", "operation": "acquire-published",
                "inputs": [{"artifact": a} for a in files],
                "parameters": {"task": {"max_bytes": 100000}, "launch": {"argv": [
                    "python", "-m", "ravel.workflow.resource_census", "--fetch-published-data", "--record-source",
                    "@input:inputs.route:outputs/route_analysis.json", "--out", "hepdata", "--download-likelihood",
                    "--tables"]}},
                "outputs": [{"path": "outputs/hepdata/hepdata_manifest.json"}]}
        output = tmp_path / "outputs"
        result = execution.acquire(step, {"run_dir": str(tmp_path)}, output_root=output, inputs=list(files.values()))
        return output, result, fetched
    return run


def test_an_acquisition_without_a_published_record_is_typed_not_applicable(acquisition):
    output, result, fetched = acquisition({"hepdata_record": None}, NO_TARGET)
    assert fetched == [], "nothing is fetched"
    manifest = json.loads((output / "hepdata/hepdata_manifest.json").read_text())
    assert manifest["status"] == "not_applicable" and manifest["tables"] == [] and manifest["likelihood"] is None
    assert manifest["evidence"]["rung"] == "reading/targets"
    assert result["exit_status"] == 0
    assert result["quantity_transport"]["representation"] == "metadata"
    assert result["quantity_transport"]["source_quantities"] == ["text"]
    assert "embedded_inventory" not in result


def test_a_census_that_found_an_analysis_keeps_the_record_refusal(acquisition):
    found = {"schema_version": 1, "records": [{"analysis_id": "fictional", "rungs": {"hepdata": {"status": "OK"}}}]}
    with pytest.raises(ValueError, match="publication record identifier: the census found an analysis"):
        acquisition({"hepdata_record": None}, found)


def test_an_absent_record_field_cannot_become_not_applicable(acquisition):
    with pytest.raises(ValueError, match="explicit hepdata_record field"):
        acquisition({}, NO_TARGET)


def test_a_named_record_is_still_fetched(acquisition):
    _, _, fetched = acquisition({"hepdata_record": "123"}, NO_TARGET)
    assert fetched and fetched[0][1:3] == ["--inspire", "123"]


@pytest.mark.parametrize("record", ["", "-x", "a b", 7])
def test_a_malformed_record_is_still_refused(acquisition, record):
    with pytest.raises(ValueError, match="nonempty publication record"):
        acquisition({"hepdata_record": record}, NO_TARGET)


def test_the_acquire_evidence_accepts_not_applicable_only_with_its_evidence(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path, NO_TARGET)
    step = next(s for s in plan["steps"] if s["id"] == "acquire.data")
    census_sha = adopt(store, tmp_path, "inputs.census", "outputs/inputs/resource_census.json", NO_TARGET)
    route = {**evidence_set()["inputs.route"]["outputs/route_analysis.json"], "hepdata_record": None}
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route)
    manifest = {"schema_version": 1, "status": "not_applicable", "reason": "no published record",
                "evidence": {"census": "inputs.census:outputs/inputs/resource_census.json",
                             "census_sha256": census_sha, "rung": "reading/targets"},
                "tables": [], "likelihood": None}
    adopt(store, tmp_path, "acquire.data", "outputs/hepdata/hepdata_manifest.json", manifest)
    ctx = context(store, tmp_path, plan, read, con, states)
    assert evidence.check(step, {"status": "completed"}, ctx) == []
    # A route analysis that names a record cannot leave its data unacquired.
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", {**route, "hepdata_record": "123"})
    codes = {e["code"] for e in evidence.check(step, {"status": "completed"}, ctx)}
    assert codes == {"acquisition_not_applicable_unsupported"}
    # An omitted field is not the explicit null required for typed absence.
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json",
          {key: value for key, value in route.items() if key != "hepdata_record"})
    codes = {e["code"] for e in evidence.check(step, {"status": "completed"}, ctx)}
    assert codes == {"acquisition_not_applicable_unsupported"}
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route)
    # A census that found an analysis, or a manifest bound to other census bytes, is refused too.
    adopt(store, tmp_path, "acquire.data", "outputs/hepdata/hepdata_manifest.json",
          {**manifest, "evidence": {**manifest["evidence"], "census_sha256": "0" * 64}})
    codes = {e["code"] for e in evidence.check(step, {"status": "completed"}, ctx)}
    assert codes == {"acquisition_not_applicable_unsupported"}
