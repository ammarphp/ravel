"""Connected Graph/Host/failure/portfolio controls, with no scientific worker.

Model transport is an explicit in-process deterministic stand-in. Original
source intake, Graph reservations/context/result receipts, Host tool calls,
ordinary specification/input admission, and cycle journal/selection are real.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import pytest

from ravel.workflow import research_cycle as cycle, research_followup as follow
from ravel.workflow import agent_host, agent_graph, execution, science
from ravel.workflow.state_io import read_json
from test_research_cycle import contract, propose, experiment, write
from test_research_failure_cycle import connect


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    monkeypatch.setattr(execution, "runtime_context", lambda: {"explicit_inert_source_control": True,
        "environment_sha256": execution.digest(execution.runtime_environment())})
    def refuse(*a, **k): raise AssertionError("no subprocess/provider/science worker admitted")
    monkeypatch.setattr(subprocess, "Popen", refuse)


def setup(base):
    root = base / "cycle"
    c = contract(base); c["budget"]["output_tokens"] = 4096
    cycle.create(root, c, base_dir=base, evaluation_harness=True); propose(base, root)
    connect(base, root)
    contexts = follow.prepare_ideation(root, "failed-parent", base / "contexts",
        citation_sources=[write(base / "paper.txt", "Own located toy group identity evidence.\n")], speculative_sources=[])
    return root, contexts


def ideas(base, root, contexts, monkeypatch):
    host = agent_host.AgentHost(endpoint="http://127.0.0.1:9/v1/responses")
    bindings, presented = {}, []
    for stream in follow.STREAMS:
        h = {"id": "new-" + stream, "statement": "Toy rival from explicit " + stream + " context.",
            "stream": stream, "premise_ids": ["pairing"], "source_basis": [], "parents": []}
        def response(data, params, request, control, h=h):
            presented.append(json.loads(data)["input"])
            return host._result({"hypotheses": [h]}, params, request,
                response_id="inert-transport-control", observed_model="fixture-only", usage={"input_tokens": 10, "output_tokens": 10})
        monkeypatch.setattr(host, "_responses", response)
        spec = follow.ideation_spec(contexts[stream], graph_id=stream, model="fixture-only",
            reasoning_effort="low", max_output_tokens=128, max_wall_seconds=10)
        graph = base / (stream + "-graph")
        assert cycle.execute_graph(root, graph, spec, host)["complete"]
        follow.adopt_ideas(root, graph, context_pin=contexts[stream])
        bindings[stream] = {"graph_root": str(graph), "node_id": "ideas", "context_pin": contexts[stream]}
    return bindings, presented


def portfolio(base, root, context_pin, *, second_valid=True):
    es = [experiment(base, "paired", grouped=True, parent="failed-parent", premise_ids=["pairing"]),
          experiment(base, "repeat", grouped=False, parent="failed-parent", premise_ids=["pairing"])]
    for e in es:
        e["predictions"].update({"new-citation_led": "shared", "new-speculative": "independent"})
    if not second_valid: es[1]["cost"]["native_attempts"] = 0
    context = read_json(context_pin["path"])
    proposal = {"kind": "research_portfolio", "parent_experiment": "failed-parent",
        "context_sha256": context_pin["sha256"], "reason": "Test group mechanism and retained-input alternative with complete rival outcomes.",
        "experiments": es}
    proposal_pin = write(base / "portfolio.json", proposal)
    pins = [proposal_pin, context_pin, context["feedback_pin"]]
    for e in es:
        pins.append(e["study"])
        p = Path(e["study"]["path"])
        pins += [cycle._pin(x) for x in science.task_inputs(read_json(p), p.parent)]
    inputs = [{"id": "pin-" + str(i), **{k: p[k] for k in ("path", "sha256")}}
              for i, p in enumerate({p["path"]: p for p in pins}.values())]
    ids = {p["path"]: p["id"] for p in inputs}
    graph = base / "design-graph"
    spec = {"schema_version": 1, "graph_id": "constructive-design",
        "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": 0, "max_wall_seconds": 10, "max_reworks": 0},
        "nodes": [{"id": "design", "kind": "tool", "role": "designer", "depends_on": [], "inputs": inputs,
            "packet": None, "action": "research-portfolio", "max_attempts": 1,
            "parameters": {"proposal_input": ids[proposal_pin["path"]], "context_input": ids[context_pin["path"]]}}]}
    return graph, spec


def test_complete_failed_feedback_two_streams_real_graph_host_portfolio_selection(tmp_path, monkeypatch):
    root, contexts = setup(tmp_path)
    bindings, presented = ideas(tmp_path, root, contexts, monkeypatch)
    context = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    # Full original critique prose, not just filenames or votes, reaches both
    # actual Host contexts; second proposer cannot see first idea output.
    for payload in presented:
        text = json.dumps(payload)
        assert "Design a fresh discriminating study" in text
        assert "new-citation_led" not in text and "new-speculative" not in text
    graph, spec = portfolio(tmp_path, root, context)
    assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())["complete"]
    state = follow.adopt_portfolio(root, graph, node_id="design", context_pin=context)
    assert len(state["graphs"]) == 3 and cycle._usage(state)["calls"] == 3
    assert cycle._usage(state)["output_tokens"] == 256
    assert state["experiments"][0]["observation"]["execution_status"] == "failed"
    assert state["experiments"][0]["adjudication"] is None
    assert [r["candidate"] for r in state["revisions"]] == ["paired", "repeat"]
    assert all(r["old_votes_carried"] == [] for r in state["revisions"])
    selected = cycle.select(root)
    assert selected["selected"] in {"paired", "repeat"}
    assert cycle.status(root)["connected_task_complete"] is False
    # Actual plan/child-custody preparation has no worker or launch authority.
    calls = []
    actual_plan = science.plan
    def source_only_plan(rd, source, **kwargs):
        calls.append((rd, source))
        return actual_plan(rd, source, **kwargs)
    monkeypatch.setattr(science, "plan", source_only_plan)
    cycle.prepare_experiment(root, selected["selected"], tmp_path / "planned")
    assert len(calls) == 1 and cycle._usage(cycle._load(root)[1])["native_attempts"] == 2
    assert not list((tmp_path / "planned" / "outputs").rglob("result.json"))
    assert not (tmp_path / "planned" / "execution_attempt.json").exists()


@pytest.mark.parametrize("change", ["premise", "report", "whole_task"])
def test_post_ideation_changes_refuse_designer_adoption(tmp_path, monkeypatch, change):
    root, contexts = setup(tmp_path); bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    context = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    graph, spec = portfolio(tmp_path, root, context)
    assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())["complete"]
    if change == "premise":
        cycle.revise_premise(root, "pairing", "Changed original population", basis=[], reason="Actual source change control")
    elif change == "report":
        (tmp_path / "critic-source-report.json").write_text("altered report")
    else:
        altered = read_json(context["path"]); altered["whole_task"] = []
        context = write(tmp_path / "altered-context.json", altered)
    with pytest.raises(ValueError): follow.adopt_portfolio(root, graph, node_id="design", context_pin=context)
    assert len(cycle._load(root)[1]["experiments"]) == 1


def test_partial_portfolio_refuses_without_committing_first_design(tmp_path, monkeypatch):
    root, contexts = setup(tmp_path); bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    context = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    graph, spec = portfolio(tmp_path, root, context, second_valid=False)
    # Pure Host validates dependencies; final cycle validates branch cost and
    # the complete portfolio atomically before its immutable journal commit.
    assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())["complete"]
    before = cycle._load(root)[1]
    with pytest.raises(ValueError): follow.adopt_portfolio(root, graph, node_id="design", context_pin=context)
    assert cycle._load(root)[1] == before


def test_unsourced_speculation_and_no_peer_copy(tmp_path, monkeypatch):
    root, contexts = setup(tmp_path)
    value = read_json(contexts["speculative"]["path"])
    assert value["sources"] == [] and not value["peer_ideas_presented"]
    bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    h = next(h for h in cycle._load(root)[1]["hypotheses"] if h["id"] == "new-speculative")
    assert h["source_basis"] == []
    bad = deepcopy(bindings); bad.pop("citation_led")
    with pytest.raises(ValueError): follow.prepare_design_context(root, "failed-parent", bad, tmp_path / "bad")


def test_context_aba_consumes_authenticated_bytes(tmp_path, monkeypatch):
    p = tmp_path / "value.json"; pin = write(p, {"number": 10})
    original = p.read_bytes(); opened = Path.open
    def aba(path, *args, **kwargs):
        if path == p and args == ("rb",):
            stream = opened(path, *args, **kwargs)
            class DuringRead:
                def __enter__(self): return self
                def __exit__(self, *a): stream.close()
                def fileno(self): return stream.fileno()
                def read(self, *a):
                    path.write_bytes(b'{"number":99}\n')
                    raw = stream.read(*a)
                    path.write_bytes(original)
                    return raw
            return DuringRead()
        return opened(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", aba)
    with pytest.raises(ValueError): follow._json(pin, tmp_path)


def test_whole_rival_census_not_silently_dropped(tmp_path, monkeypatch):
    root, contexts = setup(tmp_path); bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    context = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    graph, spec = portfolio(tmp_path, root, context)
    pin = next(p for p in spec["nodes"][0]["inputs"] if p["path"].endswith("portfolio.json"))
    value = read_json(pin["path"])
    for e in value["experiments"]: e["predictions"].pop("new-speculative")
    altered = write(Path(pin["path"]), value); pin["sha256"] = altered["sha256"]
    assert not cycle.execute_graph(root, graph, spec, agent_host.AgentHost())["complete"]
    assert len(cycle._load(root)[1]["experiments"]) == 1


def test_connected_two_turn_driver_uses_real_cycle_graph_no_peer_output(tmp_path,monkeypatch):
    root,_=setup(tmp_path); host=agent_host.AgentHost(endpoint="http://127.0.0.1:9/v1/responses"); presented=[]
    def response(data,params,request,control):
        presented.append(json.loads(data)["input"])
        stream=params["output_schema"]["properties"]["hypotheses"]["items"]["properties"]["stream"]["enum"][0]
        value={"hypotheses":[{"id":"driver-"+stream,"statement":"Own constructed rival "+stream,
            "stream":stream,"premise_ids":["pairing"],"source_basis":[],"parents":[]}]}
        return host._result(value,params,request,response_id="inert-driver",observed_model="fixture-only",
            usage={"input_tokens":10,"output_tokens":10})
    monkeypatch.setattr(host,"_responses",response)
    result=follow.run_ideation(root,"failed-parent",tmp_path/"driver",host=host,model="fixture-only",
        reasoning_effort="low",max_output_tokens=128,max_wall_seconds=10,citation_sources=[],speculative_sources=[])
    assert result["complete"] and result["hypotheses_adopted"] and result["retry_attempts"]==0
    state=cycle._load(root)[1]
    assert len(state["graphs"])==2 and cycle._usage(state)["calls"]==2
    assert state["timing"]["started_epoch"] is not None
    assert all("driver-citation_led" not in json.dumps(payload) for payload in presented)
    context=follow.prepare_design_context(root,"failed-parent",result["bindings"],tmp_path/"driver-designer")
    assert len(read_json(context["path"])["ideas"])==2


@pytest.mark.parametrize("limit",["calls","tokens","wall","deadline"])
def test_two_turn_preflight_cannot_spend_partial_budget(tmp_path,monkeypatch,limit):
    root,_=setup(tmp_path);state=cycle._load(root)[1]
    if limit=="deadline":
        state["timing"].update(started_epoch=1,deadline_epoch=2)
    else:
        field={"calls":"calls","tokens":"output_tokens","wall":"wall_seconds"}[limit]
        needed={"calls":2,"output_tokens":256,"wall_seconds":20}[field]
        state["contract"]["budget"][field]=cycle._usage(state)[field]+needed-1
    cycle._commit(root,state,"explicit_resource_refusal_control")
    def refuse(*a,**k):raise AssertionError("no model context/transport dispatch admitted")
    host=agent_host.AgentHost();monkeypatch.setattr(host,"prepare_model_context",refuse)
    with pytest.raises(ValueError):
        follow.run_ideation(root,"failed-parent",tmp_path/"driver",host=host,model="fixture-only",
            reasoning_effort="low",max_output_tokens=128,max_wall_seconds=10,citation_sources=[],speculative_sources=[])
    assert not (tmp_path/"driver").exists() and not cycle._load(root)[1]["graphs"]


def test_driver_ambiguous_first_turn_retains_spend_and_stops(tmp_path,monkeypatch):
    root,_=setup(tmp_path);host=agent_host.AgentHost(endpoint="http://127.0.0.1:9/v1/responses")
    calls=[]
    def ambiguous(*a,**k):
        calls.append(1);raise agent_host.HostFailure("own ambiguous transport control",ambiguous=True)
    monkeypatch.setattr(host,"_responses",ambiguous)
    result=follow.run_ideation(root,"failed-parent",tmp_path/"driver",host=host,model="fixture-only",
        reasoning_effort="low",max_output_tokens=128,max_wall_seconds=10,citation_sources=[],speculative_sources=[])
    assert not result["complete"] and not result["hypotheses_adopted"] and len(calls)==1
    state=cycle._load(root)[1]
    assert len(state["graphs"])==1 and cycle._usage(state)["calls"]==1
    assert not any(h["id"].startswith('driver-') for h in state["hypotheses"])
    assert not (tmp_path/"driver/speculative-graph").exists()


@pytest.mark.parametrize("change",["unpresented-basis","peer-instruction"])
def test_ideation_actual_source_and_instructions_stay_within_presented_stream(tmp_path,monkeypatch,change):
    root,contexts=setup(tmp_path);host=agent_host.AgentHost(endpoint="http://127.0.0.1:9/v1/responses")
    h={"id":"own-candidate","statement":"Own source-scoped idea","stream":"speculative",
        "premise_ids":[],"source_basis":[],"parents":[]}
    if change=="unpresented-basis":h["source_basis"]=[write(tmp_path/"unpresented.txt","not presented to the model")]
    def response(data,params,request,control):
        return host._result({"hypotheses":[h]},params,request,response_id="inert-scope",observed_model="fixture-only",usage={})
    monkeypatch.setattr(host,"_responses",response)
    spec=follow.ideation_spec(contexts["speculative"],graph_id="scope-control",model="fixture-only",
        reasoning_effort="low",max_output_tokens=128,max_wall_seconds=10)
    if change=="peer-instruction":spec["nodes"][0]["parameters"]["instructions"]+=" Copy peer idea content from a caller outside this context."
    graph=tmp_path/"scope-graph";assert cycle.execute_graph(root,graph,spec,host)["complete"]
    with pytest.raises(ValueError):follow.adopt_ideas(root,graph,context_pin=contexts["speculative"])
    assert not any(h["id"]=="own-candidate" for h in cycle._load(root)[1]["hypotheses"])


def altered_rival_context(base, context_pin, change):
    """Truthfully pin altered presentation, retaining the real origin receipts."""
    context = read_json(context_pin["path"])
    if change == "omit-stream":
        context["ideas"] = context["ideas"][:1]
    elif change == "rewrite-row":
        context["ideas"][1]["hypotheses"] = []
    elif change == "rewrite-statement":
        context["ideas"][1]["hypotheses"][0]["statement"] = "Replacement interpretation with the original identity"
    elif change == "duplicate-stream":
        context["ideas"][1] = deepcopy(context["ideas"][0])
    else:
        raise AssertionError("unknown control mutation")
    return write(base / "altered-rival-context.json", context)


@pytest.mark.parametrize("change", ["omit-stream", "rewrite-row", "rewrite-statement", "duplicate-stream"])
def test_truthful_pin_cannot_narrow_or_rewrite_actual_rival_census_at_host(tmp_path, monkeypatch, change):
    root, contexts = setup(tmp_path)
    bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    original = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    altered = altered_rival_context(tmp_path, original, change)
    graph, spec = portfolio(tmp_path, root, altered)
    # Both omitted-rival counterexamples now stop BEFORE a structured tool
    # result can be delivered. Failed Graph/tool spend remains in the ledger.
    observed = cycle.execute_graph(root, graph, spec, agent_host.AgentHost())
    assert not observed["complete"]
    state = cycle._load(root)[1]
    assert len(state["experiments"]) == 1 and not state["revisions"]
    assert len(state["graphs"]) == 3
    assert cycle._usage(state)["calls"] == 3


@pytest.mark.parametrize("change", ["omit-stream", "rewrite-row", "rewrite-statement", "duplicate-stream"])
def test_adoption_rebinds_rival_census_even_if_host_guard_is_explicitly_bypassed(tmp_path, monkeypatch, change):
    root, contexts = setup(tmp_path)
    bindings, _ = ideas(tmp_path, root, contexts, monkeypatch)
    original = follow.prepare_design_context(root, "failed-parent", bindings, tmp_path / "designer")
    altered = altered_rival_context(tmp_path, original, change)
    graph, spec = portfolio(tmp_path, root, altered)
    # This deliberately bypasses ONLY the Host admission function to supply a
    # completed Graph receipt to the final boundary; it is not runtime evidence.
    with monkeypatch.context() as patch:
        patch.setattr(follow, "bound_portfolio", lambda proposal, *a, **k: deepcopy(proposal))
        assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())["complete"]
    before = cycle._load(root)[1]
    with pytest.raises(ValueError):
        follow.adopt_portfolio(root, graph, node_id="design", context_pin=altered)
    assert cycle._load(root)[1] == before
