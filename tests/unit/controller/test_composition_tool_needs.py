"""Composed inert runs: the controller plans with the best available tool for a capability need.

The wave-A composition (real ledger, authority, instructions, confinement, judgment and step graph, the restricted
CLI worker transport in the OS sandbox) drives one request whose wording raises the routine-construction need up to
CHECK-IN 1, which the operator keeps for a human. The inert planner always proposes a hand-written analysis first and
follows the controller's correction when it names the need. Only the host's tool facts are stood in, at their
source (``environment_profile.PROBES['tools']``): with the preferred construction tool installed the controller
refuses the first plan and installs the corrected one; with it missing the hand-written analysis is the best
available candidate and the first plan is installed. Either way the run keeps one environment profile, one
``tool-selection`` record per installed plan and obligation CT09 recorded from that check. A request of three parts
(a routine to construct, a global fit, a symbolic derivation) is planned by an inert planner that reads the
controller's capability view as data: each part gets its own best available tool, the missing or unlicensed tools fall
back for their own part only, and the need that does not arise gets no step. The original planning controls stop at
CHECK-IN 1. Execution controls answer it through real operator authority and resume the checkpoint. Plans without
closed native task declarations retain their approval refusal. Closed tasks execute through the native boundary;
the synthesis consumes every selected part's accepted output. The unrelated executable sentinel must stay idle.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import re
from pathlib import Path

import pytest

import test_composition_wave_a as wave
from ravel.controller import entry, testing
from ravel.controller.ledger import state as ledger_state
from ravel.setup import environment_profile

AGENTRIVET = "census-agentrivet-e4d12ecc"
# The wave-A request (a research parent on the judgment route) with a sentence that raises the need from its wording
# alone: it adds no reading constraint, so the inert frame stays complete.
REQUEST = wave.REQUEST + b" Derive the value without a published routine."
HAND_WRITTEN = '''
    write = {"id": "write-analysis", "kind": "operate", "operation": "authored-analysis", "role": "analysis-author",
             "purpose": "Write the particle-level selection of the fictional search by hand.",
             "inputs": [{"artifact": "reading"}],
             "outputs": [{"path": "outputs/analysis.json", "kind": "result", "required": True}],
             "depends_on": [], "budget_share": {"fraction": 0.2}, "protocols": [], "review": [], "obligations": []}
    construct = {"id": "construct-routine", "kind": "author", "role": "routine-constructor",
                 "purpose": "Construct the routine of the fictional search with the agentic construction roles.",
                 "inputs": [{"artifact": "reading"}],
                 "outputs": [{"path": "outputs/routine.json", "kind": "result", "required": True}],
                 "depends_on": [], "budget_share": {"fraction": 0.2}, "protocols": [], "review": [],
                 "obligations": []}
    # A naive planner: the controller's feedback in its declared context names the better plan form.
    corrected = any("routine-constructor" in str(problem) for problem in context.get("feedback") or ())
    steps.insert(0, construct if corrected else write)
'''


def worker_source():
    """The wave-A inert worker whose planner adds the routine step (hand-written unless corrected)."""
    anchor = "    steps = [derive]\n"
    assert wave.WORKER.count(anchor) == 1
    return wave.WORKER.replace(anchor, anchor + HAND_WRITTEN)


def fact(readiness, status, licence="not_applicable"):
    return {"readiness": readiness, "status": status, "version": None, "licence": licence,
            "platform_qualification": ""}


READY, MISSING = fact("ready", "built_but_unqualified"), fact("missing", "not_installed")


def tool_facts(rows):
    def probe(**_):
        return {"observed": True, "source": "doctor-census", "prefix": None, "reason": None, "rows": dict(rows)}
    return probe


def drive_to_checkin1(tmp_path, monkeypatch, *, rows, request=REQUEST, worker=None, supplied_files=None):
    """The wave-A setup with CHECK-IN 1 kept for a human: the run plans, reviews the plan and waits."""
    from ravel.workflow import agent_tripwire, sandbox
    if sandbox.available() is None:
        pytest.fail("the composed run needs the OS worker sandbox; this host offers none")
    root = Path(os.path.realpath(tmp_path))
    for name in ("state", "home", "claude-login", "bin", "operator"):
        (root / name).mkdir()
    monkeypatch.setenv("RAVEL_STATE_DIR", str(root / "state"))
    monkeypatch.setenv("HOME", str(root / "home"))
    for name in ("RAVEL_WORK_ROOT", "RAVEL_TRANSPORT_PATH", "RAVEL_AGENT_TRIPWIRE", "RAVEL_OPERATING_MODE",
                 "RAVEL_RESTRICTED_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    confine = importlib.import_module("ravel.controller.confine")
    identity = importlib.import_module("ravel.controller.confine.identity")
    for holder in (identity, confine):
        monkeypatch.setattr(holder, "code_identity", lambda **_: dict(wave.INSTALLED))
    monkeypatch.setattr(wave, "WORKER", worker or worker_source())
    monkeypatch.setitem(environment_profile.PROBES, "tools", tool_facts(rows))
    sources = root / "operator" / "restricted-sources.json"
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    preferences = wave._install_worker(root, monkeypatch)
    from ravel.workflow import provider_policy, transport_registry
    transport = transport_registry.load(wave.TRANSPORT)
    classification = {'level': 'public', 'allowed_providers': [
        {'transport_id': transport['id'], 'account_class': provider_policy.account_class(transport)}]}
    supplied = []
    for name, content in (supplied_files or {}).items():
        path = root / 'operator' / name
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        supplied.extend(entry._supplied(['file=' + str(path)], str(root),
                                       data_classification=classification))
    sentinel = root / 'bin' / 'snakemake'
    sentinel.write_text('#!/bin/sh\nprintf invoked > ' + str(root / 'sentinel-effect') + '\nexit 91\n')
    sentinel.chmod(0o700)
    status, output = wave._operator("init", "--mode", "autonomous", "--store-root", str(root / "store"),
                                    "--machine-checkins", "go,deviation,final", "--wait-bound", "3600",
                                    "--allow-unconfined", "false", "--restricted-sources", str(sources),
                                    "--agent-preferences", json.dumps(preferences))
    assert status == 0, output
    store = entry.start(request, channel="operator-file", rundir=root / "runs" / "r1", unattended=True,
                        supplied=supplied,
                        origin={"entry": "drive", "source": "request-file", "channel": "operator-file"})
    wave._qualify(root, store)
    try:
        with testing.seams(False, controller=True):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                observation = entry.drive(store, unattended=False, sleep=lambda seconds: None, poll_seconds=0)
        if any(r.get('reason') == 'exception' for r in records(store, 'qualified-ending')):
            from ravel.workflow import graph_substrate
            _, _, snapshot = graph_substrate._pending(store.graph_scope(), entry.GRAPH_ID, {'run_id': store.run_id})
            pytest.fail(json.dumps(snapshot.values.get('failures'), default=str))
        return store, observation, err.getvalue()
    except BaseException:
        ledger_state.forget(store)
        raise


def records(store, kind):
    return [row["record"] for row in store.scan(kind)]


def plan_events(store):
    from ravel.controller.judgment import control
    return [row for row in records(store, control.EVENT_KIND) if row.get("event") == "plan"]


def ct09(store):
    from ravel.controller import ledger
    return [row for row in ledger.current(store, node="controller.plan") if row["id"] == "CT09"]


def installed_steps(store):
    return wave._installed_plan(store)["steps"]


def planner_rounds(store):
    """Where the run stopped, with each decompose context's feedback and each written plan's step ids."""
    rows = []
    for path in sorted(Path(store.run_dir).rglob("*.json")):
        if path.name.startswith("decompose-") or path.name.endswith("judgment-plan.json"):
            try:
                doc = json.loads(path.read_text())
            except ValueError:
                continue
            rows.append({"path": str(path.relative_to(store.run_dir)), "feedback": str(doc.get("feedback"))[:300],
                         "steps": [s.get("id") for s in doc.get("steps") or () if isinstance(s, dict)]})
    return wave._where(store) + "\n" + json.dumps(rows)[:6000]


@pytest.fixture
def ready(tmp_path, monkeypatch):
    store, observation, err = drive_to_checkin1(tmp_path, monkeypatch, rows={AGENTRIVET: READY})
    yield store, observation, err
    ledger_state.forget(store)


@pytest.fixture
def missing(tmp_path, monkeypatch):
    store, observation, err = drive_to_checkin1(tmp_path, monkeypatch, rows={AGENTRIVET: MISSING})
    yield store, observation, err
    ledger_state.forget(store)


def test_the_available_construction_tool_is_selected_after_the_controller_refuses_the_hand_written_plan(ready):
    store, observation, err = ready
    pending = entry._pending(observation)
    assert pending and pending[0]["payload"]["authority_kind"] == "approve_plan", planner_rounds(store)
    profile, = records(store, "environment-profile")
    assert profile["tools"]["rows"][AGENTRIVET]["readiness"] == "ready"
    events = plan_events(store)
    refused = [e for e in events if e["status"] == "refused"]
    assert refused and any("routine-construction" in p and "routine-constructor" in p
                           for p in refused[0]["problems"]), events
    assert [e["status"] for e in events][-1] == "written"
    roles = {s.get("role") for s in installed_steps(store)}
    assert "routine-constructor" in roles and not any(s.get("operation") == "authored-analysis"
                                                    for s in installed_steps(store))
    selection = records(store, "tool-selection")[-1]
    need, = [row for row in selection["needs"] if row["need"] == "routine-construction"]
    assert selection["passed"] is True and need["best"] == AGENTRIVET and need["status"] == "served"
    row, = ct09(store)
    assert row["status"] == "satisfied" and row["evidence"]["mechanism"] == "tool_selection.check"
    assert row["evidence"]["record"] == store.scan("tool-selection")[-1]["id"]


def test_a_missing_construction_tool_falls_back_to_the_hand_written_analysis_with_its_reason(missing):
    store, observation, err = missing
    pending = entry._pending(observation)
    assert pending and pending[0]["payload"]["authority_kind"] == "approve_plan", planner_rounds(store)
    events = plan_events(store)
    assert [e["status"] for e in events] == ["written"], events
    assert any(s.get("operation") == "authored-analysis" for s in installed_steps(store))
    selection = records(store, "tool-selection")[-1]
    need, = [row for row in selection["needs"] if row["need"] == "routine-construction"]
    assert selection["passed"] is True and need["best"] == "hand-written-analysis" and need["status"] == "served"
    skipped = {c["id"]: c["reason"] for c in need["candidates"] if c["state"] == "unavailable"}
    assert skipped == {AGENTRIVET: "not_installed"}
    row, = ct09(store)
    assert row["status"] == "satisfied"


# ---- a request of several parts: each part selects its own tool ---------------------------------------------

SFITTER = "census-sfitteragents-sfitter-6072a79e-pytorch-2-14-0"
EFT_TOOLS = "census-wcxf-wilson-2-5-2-flavio-2-7-1-smelli-2-4-3"
FEYNRULES = "census-feynrules-2-3-49"
FLEXIBLESUSY = "census-flexiblesusy-2-9-0-cmssm-lowmssm-nmssm"
SYMPY = "component-sympy"
SNAKEMAKE = "census-snakemake-9-27-0"
# Three parts, three needs: a routine to construct, a global fit and a symbolic derivation. The workflow-manager
# need does not arise, although its tool is installed.
MULTI_PART = wave.REQUEST + (b" Derive the value without a published routine. Perform a global fit of the "
                             b"measurements. Derive the Feynman rules of the toy model.")
# The construction tool is installed; the fit tools are not (the Gaussian measurement fit is the qualified
# fallback); the Mathematica packages are unlicensed and no spectrum generator is installed (SymPy is the fallback).
MULTI_FACTS = {AGENTRIVET: READY, SFITTER: MISSING, EFT_TOOLS: MISSING,
               FEYNRULES: fact("unconfigured", "built_but_unqualified", licence="unlicensed"),
               FLEXIBLESUSY: MISSING, SYMPY: READY, SNAKEMAKE: READY}
CATALOGUE_PLANNER = '''
    # A planner that reads the controller's capability view (generated data, not prose): one step per need that
    # arises, through its best available candidate's plan form; a need that does not arise gets no step.
    view = next((d["tools"] for d in docs if isinstance(d, dict) and d.get("schema") == "judgment-plan.v1"
                 and isinstance(d.get("tools"), dict)), {})
    for row in view.get("needs") or ():
        if not row.get("arises") or not row.get("best"):
            continue
        best = next(c for c in row["candidates"] if c["id"] == row["best"])
        sid = "serve-" + row["need"]
        form = ({"kind": "author", "role": best["roles"][0]} if best["roles"]
                else {"kind": "operate", "operation": best["operations"][0]})
        steps.insert(0, {"id": sid, **form, "purpose": "Serve the " + row["need"] + " part with " + best["title"] + ".",
                         "inputs": [{"artifact": "reading"}],
                         "outputs": [{"path": "outputs/" + sid + ".json", "kind": "result", "required": True}],
                         "depends_on": [], "budget_share": {"fraction": 0.1}, "protocols": [], "review": [],
                         "obligations": []})
'''
# The frame carries every scope constraint the reading has (the request names a stage).
FRAME_CONSTRAINTS = '''
    reading_doc = next((d for d in docs if isinstance(d, dict) and isinstance(d.get("deliverables"), list)
                        and d.get("kind") != "question-frame"), {})
    scope = SCOPE
    framed["constraints"] = [{"kind": scope[c["type"]], "statement": "Kept from the reading: " + c["type"] + ".",
                              "reading_ref": c["id"]} for c in reading_doc.get("constraints") or ()
                             if isinstance(c, dict) and c.get("type") in scope]
'''


def catalogue_worker():
    """The wave-A inert worker with the catalogue-reading planner and a frame that keeps scope constraints."""
    from ravel.controller.judgment import planning
    source = wave.WORKER
    anchor = "    steps = [derive]\n"
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + CATALOGUE_PLANNER)
    head, ret = "def frame(docs):\n", "    return {\"schema_version\": 1, \"kind\": \"question-frame\""
    assert source.count(head) == 1 and source.count(ret) == 1
    body = source[source.index(head):]
    end = body.index(ret)
    framed = body[:end] + "    framed = " + body[end + len("    return "):]
    close = framed.index("\"boundaries\": []}") + len("\"boundaries\": []}")
    framed = (framed[:close] + "\n" + FRAME_CONSTRAINTS.replace("SCOPE", repr(planning.SCOPE_CONSTRAINTS))
              + "    return framed\n" + framed[close:])
    return source[:source.index(head)] + framed


@pytest.fixture
def multi(tmp_path, monkeypatch):
    store, observation, err = drive_to_checkin1(tmp_path, monkeypatch, rows=MULTI_FACTS, request=MULTI_PART,
                                                worker=catalogue_worker())
    yield store, observation, err
    ledger_state.forget(store)


def test_each_part_of_a_request_is_served_by_its_own_best_available_tool(multi):
    store, observation, err = multi
    pending = entry._pending(observation)
    assert pending and pending[0]["payload"]["authority_kind"] == "approve_plan", planner_rounds(store)
    assert [e["status"] for e in plan_events(store)] == ["written"], planner_rounds(store)
    forms = {s["id"]: (s.get("role"), s.get("operation")) for s in installed_steps(store) if s["id"].startswith("serve-")}
    # Each part is served through its own tool (an operation runs under its registered executor role); nothing is
    # planned for the need that does not arise.
    assert forms == {"serve-routine-construction": ("routine-constructor", None),
                     "serve-global-fit": ("inference", "measurement"),
                     "serve-symbolic-model-building": ("analysis-author", "authored-analysis")}, forms
    selection = records(store, "tool-selection")[-1]
    by_need = {row["need"]: row for row in selection["needs"]}
    assert set(by_need) == {"routine-construction", "global-fit", "symbolic-model-building"}
    assert selection["passed"] is True and all(row["status"] == "served" for row in by_need.values())
    # The installed tool serves its part; the missing or unlicensed tools fall back for their own part only.
    assert by_need["routine-construction"]["best"] == AGENTRIVET
    assert by_need["global-fit"]["best"] == "gaussian-measurement-fit"
    assert by_need["symbolic-model-building"]["best"] == SYMPY
    skipped = {c["id"]: c["reason"] for row in by_need.values() for c in row["candidates"] if c["state"] == "unavailable"}
    assert skipped == {SFITTER: "not_installed", EFT_TOOLS: "not_installed", FEYNRULES: "unlicensed",
                       FLEXIBLESUSY: "not_installed", "supplied-ufo": "requires_supplied_input:model"}
    row, = ct09(store)
    assert row["status"] == "satisfied"


# Plans without closed operation tasks remain refusal controls. The original planning controls above retain
# their original forms and assertions; positive execution below supplies real task inputs through intake.
def execution_worker():
    source = catalogue_worker()
    anchor = '    if any(METHOD_CHOICE in str(d.get("request")) for d in docs if isinstance(d, dict)):'
    assert source.count(anchor) == 1
    preparation = '''
    parts = [s for s in steps if s["id"].startswith("serve-")]
    for part in parts:
        operation = part.get("operation")
        if operation:
            part["outputs"][0]["kind"] = {"measurement": "inference", "authored-analysis": "selection"}.get(operation, "result")
            part["budget_share"].update(wall_seconds=60, events=0)
    steps.append({"id": "combine-parts", "kind": "synthesize", "purpose": "Combine the accepted outputs of all three parts.",
                  "inputs": [{"artifact": p["id"] + ":" + p["outputs"][0]["path"]} for p in parts],
                  "outputs": [{"path": "outputs/combined.json", "kind": "result", "required": True}],
                  "depends_on": [p["id"] for p in parts], "budget_share": {"fraction": 0.1},
                  "protocols": [], "review": [], "obligations": []})
'''
    source = source.replace(anchor, preparation + anchor)
    return source


def approve_and_resume(store, observation, stderr):
    """Answer the real pending CHECK-IN 1 request, then resume its persisted LangGraph checkpoint."""
    pending, = entry._pending(observation)
    assert pending["payload"]["authority_kind"] == "approve_plan", planner_rounds(store)
    code = re.findall(r"--code (\S+)", stderr)[-1]
    status, output = wave._operator("answer", "--run", store.run_id,
                                    "--request", pending["payload"]["pending"]["request"],
                                    "--code", code, "--decision", "approve")
    assert status == 0, output
    with testing.seams(False, controller=True):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            observation = entry.drive(store, unattended=False, resume=True,
                                      sleep=lambda seconds: None, poll_seconds=0)
    approvals = [r for r in records(store, "authority") if r.get("kind") == "approve_plan"]
    assert approvals and approvals[-1]["decision"] == "approve", planner_rounds(store)
    return observation, err.getvalue()


@pytest.mark.parametrize("construction_available", [True, False], ids=["tool-present", "tool-missing"])
def test_approved_parts_hold_at_native_input_commitment_before_any_effect(
        tmp_path, monkeypatch, construction_available):
    """Planning coverage is not an execution proof: approval cannot commit the ordinary native task boundary.

    The operation output kinds and zero-event budgets are valid here, so a missing closed task adapter is exposed
    without conflating it with the original planning-only output declarations. No accepted output is fabricated to
    let the synthesis pass; its three predecessor inputs remain obligations of the approved request.
    """
    rows = {**MULTI_FACTS, AGENTRIVET: READY if construction_available else MISSING}
    store, observation, stderr = drive_to_checkin1(tmp_path, monkeypatch, rows=rows, request=MULTI_PART,
                                                  worker=execution_worker())
    try:
        steps = {s["id"]: s for s in installed_steps(store)}
        parts = {sid: s for sid, s in steps.items() if sid.startswith("serve-")}
        assert len(parts) == 3 and "combine-parts" in steps
        assert set(steps["combine-parts"]["depends_on"]) == set(parts)
        assert {r["artifact"] for r in steps["combine-parts"]["inputs"]} == {
            sid + ":" + step["outputs"][0]["path"] for sid, step in parts.items()}
        selection = records(store, "tool-selection")[-1]
        assert selection["passed"] and all(n["status"] == "served" for n in selection["needs"])
        assert "external-workflow-execution" not in {n["need"] for n in selection["needs"]}
        profile, = records(store, "environment-profile")
        assert profile["tools"]["rows"][SNAKEMAKE]["readiness"] == "ready"
        observation, stderr = approve_and_resume(store, observation, stderr)
        native = {sid for sid, s in parts.items() if s["kind"] == "operate"}
        endings = records(store, "qualified-ending")
        assert endings and endings[-1]["reason"] == "operation_input_commitment_refused", planner_rounds(store)
        assert records(store, "operation-input-commitment") == []
        effects = {kind: [r for r in records(store, kind) if r.get("step_id") in {*parts, "combine-parts"}]
                   for kind in ("step-outcome", "step-launch", "step-dispatch", "custody")}
        assert all(rows == [] for rows in effects.values()), effects
        # Zero completed parts means the declared synthesis cannot consume accepted outputs or be dispatched.
        assert not [r for r in records(store, "custody")
                    if r.get("artifact") in {i["artifact"] for i in steps["combine-parts"]["inputs"]}]
        unrelated = {sid for sid, s in steps.items() if s.get("operation") == "external-workflow"}
        assert unrelated == set()
        unrelated_effects = [r for kind in ("step-dispatch", "step-launch") for r in records(store, kind)
                             if r.get("step_id") in unrelated]
        assert unrelated_effects == []
        print("EXECUTION_GAP=" + json.dumps({"native": sorted(native), "ending": endings[-1]["reason"],
                                             "effects": {kind: len(rows) for kind, rows in effects.items()},
                                             "synthesis": "blocked", "unrelated_effects": len(unrelated_effects)}, default=str))
    finally:
        ledger_state.forget(store)
