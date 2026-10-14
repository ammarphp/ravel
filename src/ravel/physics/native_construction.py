"""Source-only native routine proposals through the existing AgentHost graph.

This materializes an actual public model reply into an *unreviewed* source
capsule and a prospective routine-build configuration. It neither imports the
candidate nor runs a compiler. Independent dependency review, a freshly sealed
build plan and the ordinary scientific-study lifecycle are still required.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

from ravel import analysis_sources as sources
from ravel.workflow import agent_graph
from ravel.workflow.agent_host import validate_public_result
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, file_lock, read_json

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
MAX_SOURCE_BYTES = 2_000_000


def _keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError("closed native construction fields required: " + ", ".join(names))


def _pin(pin, base):
    _keys(pin, ("path", "sha256"))
    path = regular(pin["path"], base)
    if sources.digest(path) != pin["sha256"]:
        raise ValueError("native construction input bytes differ")
    return path


def _name(value):
    if type(value) is not str or not NAME.fullmatch(value):
        raise ValueError("bounded literal native routine identity required")
    return value


def _identifier(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise ValueError("bounded source claim/obligation identity required")
    return value


def _list(value, maximum, *, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError("bounded native construction population required")


def _text(value, maximum):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded nonempty native construction text required")
    return value


def _span(path, first, last):
    lines = path.read_bytes().splitlines(keepends=True)
    if (type(first) is not int or type(last) is not int or
            not 1 <= first <= last <= len(lines)):
        raise ValueError("exact positive source line span required")
    raw = b"".join(lines[first - 1:last])
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def _load(path):
    path = regular(path, Path.cwd())
    config = read_json(path)
    optional = {k for k in ("improvement_lineage", "continuation_campaign", "support_sources") if k in config}
    _keys(config, ("schema_version", "kind", "source_capsule", "target_routine",
        "source_claims", "obligations", "api_sources", "build_template",
        "requested_task", "max_source_bytes", *optional))
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["kind"] != "native-routine-construction":
        raise ValueError("native routine construction/v1 required")
    if type(config["max_source_bytes"]) is not int or not 1 <= config["max_source_bytes"] <= MAX_SOURCE_BYTES:
        raise ValueError("explicit bounded source context required")
    _text(config["requested_task"], 32000)
    target = _name(config["target_routine"])
    capsule_path = _pin(config["source_capsule"], path.parent)
    capsule = sources.load_capsule(capsule_path)
    if capsule["framework"] != "rivet" or target == capsule["routine"]:
        raise ValueError("a distinct Rivet candidate name is required")
    root, files = sources.source_files(capsule, capsule_path.parent)
    facts = {fact["path"]: fact for fact in capsule["files"]}
    units = [f["path"] for f in capsule["files"] if f["role"] == "compile"]
    bindings = sources.routine_bindings(capsule, capsule_path.parent, units)
    if bindings[capsule["routine"]]["registration"] == "declared-capsule-primary":
        raise ValueError("original routine needs a positive literal registration")
    _list(config["source_claims"], 256, minimum=1)
    claims, claim_ids = [], set()
    for claim in config["source_claims"]:
        _keys(claim, ("id", "path", "line_start", "line_end", "excerpt_sha256"))
        _identifier(claim["id"])
        if claim["id"] in claim_ids or claim["path"] not in facts:
            raise ValueError("duplicate or foreign source claim")
        text, sha = _span(root / claim["path"], claim["line_start"], claim["line_end"])
        if sha != claim["excerpt_sha256"]:
            raise ValueError("native source claim span changed")
        claims.append({**claim, "text": text}); claim_ids.add(claim["id"])
    _list(config["obligations"], 64, minimum=1)
    obligations = set()
    for obligation in config["obligations"]:
        _keys(obligation, ("id", "description")); _identifier(obligation["id"])
        _text(obligation["description"], 8000)
        if obligation["id"] in obligations:
            raise ValueError("duplicate source obligation")
        obligations.add(obligation["id"])
    _list(config["api_sources"], 32, minimum=1)
    api = []
    for fact in config["api_sources"]:
        _keys(fact, ("path", "sha256", "line_start", "line_end"))
        source = _pin({k: fact[k] for k in ("path", "sha256")}, path.parent)
        text, span_sha = _span(source, fact["line_start"], fact["line_end"])
        api.append({**fact, "excerpt_sha256": span_sha, "text": text})
    template_path = _pin(config["build_template"], path.parent)
    template = read_json(template_path)
    _keys(template, ("schema_version", "source_capsule", "recipe", "runtime", "probe", "execution_identity"))
    if template.get("recipe", {}).get("name") != "rivet-plugin" or template.get("schema_version") != 2 or not template.get("execution_identity"):
        raise ValueError("explicit sealed Rivet runtime template required")
    runtime_facts = template["runtime"]["artifacts"] + list(template["runtime"]["tools"].values())
    for fact in api:
        if not any(str(regular(bound["path"], template_path.parent)) == str(regular(fact["path"], path.parent))
                   and bound["sha256"] == fact["sha256"] for bound in runtime_facts):
            raise ValueError("API header is not bound to the selected runtime template")
    # Whole implementation and human-readable metadata, never held-out events,
    # output numbers, previous candidates or a producer-authored answer program.
    texts = []
    total = 0
    for fact in capsule["files"]:
        p = root / fact["path"]; size = p.stat().st_size; total += size
        if total > config["max_source_bytes"]:
            raise ValueError("declared source byte bound exceeded")
        if fact["role"] in ("compile", "header", "configuration") or p.suffix == ".plot":
            texts.append({**fact, "text": p.read_text(encoding="utf-8")})
    if total + sum(len(row["text"].encode()) for row in api) > config["max_source_bytes"]:
        raise ValueError("combined source/API byte bound exceeded")
    support = []
    for fact in config.get("support_sources", []):
        _keys(fact, ("path", "sha256", "description"))
        p = _pin({k: fact[k] for k in ("path", "sha256")}, path.parent)
        _text(fact["description"], 8000)
        support.append({**fact, "text": p.read_text(encoding="utf-8")})
    _list(support, 16)
    if len({f["path"] for f in support}) != len(support):
        raise ValueError("distinct support source paths required")
    if total + sum(len(r["text"].encode()) for r in api + support) > config["max_source_bytes"]:
        raise ValueError("combined source/API/support byte bound exceeded")
    lineage = None
    if "improvement_lineage" in config:
        from . import native_incumbent
        lineage = native_incumbent.validate_lineage(config["improvement_lineage"], path.parent)
        parent_path = native_incumbent.bound(lineage["construction"], path.parent)
        parent_config = read_json(parent_path)
        claims_by_id = {row["id"]: row for row in config["source_claims"]}
        obligations_by_id = {row["id"]: row for row in config["obligations"]}
        if (capsule_path != _pin(parent_config["source_capsule"], parent_path.parent) or
                target == lineage["source_routine"] or
                any(claims_by_id.get(row["id"]) != row for row in parent_config["source_claims"]) or
                any(obligations_by_id.get(row["id"]) != row for row in parent_config["obligations"])):
            raise ValueError("improvement must retain source claims/obligations and use a distinct challenger identity")
    if "continuation_campaign" in config:
        if lineage is None:
            raise ValueError("continuation campaign requires its successful incumbent lineage")
        native_incumbent.validate_campaign(config["continuation_campaign"], path.parent,
                                           config["improvement_lineage"])
    return {"config": config, "path": path, "capsule": capsule,
            "capsule_path": capsule_path, "root": root, "files": files,
            "claims": claims, "api": api, "source_text": texts,
            "template_path": template_path, "template": template,
            "support": support, "lineage": lineage}


def output_schema(config, original):
    def array(values):
        values = list(values)
        return {"type": "array", "items": {"type": "string", "enum": list(values)}, "maxItems": len(values)}
    text = {"type": "string", "minLength": 1, "maxLength": 128000}
    props = {"schema_version": {"type": "integer", "const": 1},
        "routine_name": {"type": "string", "const": config["target_routine"]},
        "reference_data_name": {"type": "string", "const": original},
        "translation_unit": text, "metadata_info": text, "metadata_plot": text,
        "source_claim_ids": array(c["id"] for c in config["source_claims"]),
        "served_obligations": array(o["id"] for o in config["obligations"]),
        "unserved_obligations": array(o["id"] for o in config["obligations"]),
        "public_rationale": {"type": "string", "minLength": 1, "maxLength": 16000}}
    if "improvement_lineage" in config:
        props["supporting_files"] = {"type": "array", "maxItems": 16,
            "items": {"type": "object", "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 128},
                "text": text}, "required": ["path", "text"], "additionalProperties": False}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _source_packet(loaded):
    config, capsule = loaded["config"], loaded["capsule"]
    packet = {"schema_version": 1, "kind": "native-routine-source-request",
        "configuration_sha256": sources.digest(loaded["path"]),
        "requested_task": config["requested_task"], "target_routine": config["target_routine"],
        "reference_data_name": capsule["routine"],
        "source_capsule_sha256": sources.digest(loaded["capsule_path"]),
        "source_identity": capsule["source"], "source_inventory": capsule["files"],
        "source_dependency_review": capsule["dependency_review"],
        "source_text": loaded["source_text"], "source_claims": loaded["claims"],
        "obligations": config["obligations"], "installed_api": loaded["api"],
        "runtime_template_sha256": sources.digest(loaded["template_path"]),
        "runtime": loaded["template"]["runtime"],
        "output_schema": output_schema(config, capsule["routine"]),
        "withheld": ["evaluation events", "expected outputs", "other candidate implementations", "previous typed program"],
        "execution_authorized": False, "physics_validated": False,
        "instructions": "Return complete C++ plus candidate .info/.plot metadata as public JSON. Use the distinct canonical candidate name and the original reference-data identity. Preserve every applicable source obligation or explicitly mark it unserved. Do not execute tools, import code, assume withheld answers or claim scientific approval."}
    if loaded.get("support"):
        packet["support_sources"] = loaded["support"]
    if loaded.get("lineage") is not None:
        from . import native_incumbent
        lineage = loaded["lineage"]
        saved = read_json(native_incumbent.bound(lineage["parent_model_receipt"], loaded["path"].parent))
        packet.update(kind="successful-native-incumbent-improvement-request",
            revision_type="improve_successful_native_incumbent",
            improvement_lineage=deepcopy(config["improvement_lineage"]),
            improvement_objective=lineage["objective"],
            previous_public_candidate=deepcopy(saved["result"]["value"]),
            observed_incumbent={"result_sha256": lineage["parent_result"]["sha256"],
                "source_sha256": lineage["translation_unit_sha256"],
                "scope": lineage["source_scope"], "metric": deepcopy(lineage["metric"])},
            failure_trigger=None, prior_votes_carried=[])
        packet["instructions"] = "Improve the accepted source-native incumbent for the declared scientific objective. Return complete distinct C++ and metadata, plus any explicit header support files. Keep original reference identity and every original obligation; declare unserved scope. This is a fresh challenger, without a fabricated failure or inherited approval. Do not execute tools or read withheld cases/answers."
        packet["withheld"] += ["fresh held-out/full-case event rows and expected outputs", "raw parent event rows and oracle"]
        if "continuation_campaign" in config:
            packet["continuation_campaign"] = deepcopy(config["continuation_campaign"])
    return packet


def write_source_packet(config_path, output_path):
    """Capture a source-only initial proposal packet without reserving a call."""
    packet = _source_packet(_load(config_path))
    output = Path(output_path).absolute()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("native request must be a fresh ordinary path")
    atomic_json(output, packet)
    return {"path": str(output), "sha256": sources.digest(output),
            "model_executed": False, "execution_authorized": False}


def prepare_agent_request(config_path, packet_pin, graph_root, *, model,
                          reasoning_effort, max_output_tokens=16000, max_calls=2):
    """Reserve the initial call of a distinct, finite native construction task.

    This is not a reset of an existing typed construction graph. Actual repairs
    must revise this same graph after newly reviewed execution feedback; the
    initial reservation retains room for explicitly bounded, separately admitted
    turns. The default permits one initial call and one actual-failure repair.
    """
    loaded = _load(config_path)
    packet_path = _pin(packet_pin, loaded["path"].parent)
    panel = read_json(packet_path)
    if panel != _source_packet(loaded):
        raise ValueError("native proposal packet belongs to different source inputs")
    root = Path(graph_root).absolute()
    if loaded.get("lineage") is not None:
        from . import native_incumbent
        return native_incumbent.prepare_agent_request(loaded, packet_pin, root,
            model=model, reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens, max_calls=max_calls)
    if root.exists() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("new native task requires a fresh ordinary graph")
    if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000:
        raise ValueError("explicit bounded output reservation required")
    if type(max_calls) is not int or not 1 <= max_calls <= 3:
        raise ValueError("one to three explicitly bounded construction calls required")
    node = {"id": "construct", "kind": "model", "role": "proposer", "depends_on": [],
        "inputs": [{"id": "native-source", **packet_pin}], "packet": None,
        "action": "external", "max_attempts": 1,
        "parameters": {"instructions": panel["instructions"], "model": model,
            "reasoning_effort": reasoning_effort, "max_output_tokens": max_output_tokens,
            "output_schema": output_schema(loaded["config"], loaded["capsule"]["routine"])}}
    specification = {"schema_version": 1, "graph_id": "native-source-construction",
        "budget": {"max_nodes": 1, "max_calls": max_calls, "max_output_tokens": max_calls * max_output_tokens,
            "max_wall_seconds": 7200, "max_reworks": max_calls - 1}, "nodes": [node]}
    agent_graph.create(root, specification)
    return {**agent_graph.prepare_external(root, "construct"),
            "packet_pin": deepcopy(packet_pin), "model_executed": False,
            "execution_authorized": False}


def _proposal_receipt(root, packet_pin):
    """Rebind current graph inputs, response and accounted external invocation."""
    root = Path(root).resolve()
    with file_lock(root / "state.lock"):
        specification, state = agent_graph._load(root)
        node = next((n for n in specification["nodes"] if n["id"] == "construct"), None)
        current = state["nodes"].get("construct", {})
        if (state["cancelled"] or node is None or node["role"] not in ("proposer", "improver") or
                current.get("status") != "completed" or not current.get("result")):
            raise ValueError("current completed proposer/improver receipt required")
        agent_graph._artifact_checks(node)
        saved = agent_graph._result(root, current["result"])
        expected = agent_graph._request(specification, state, node, saved["host_sha256"])
        if expected != saved["request"] or node["inputs"] != [{"id": "native-source", **packet_pin}]:
            raise ValueError("native reply belongs to changed source request")
        result = saved["result"]
        if (result.get("kind") != "model_result" or
                result.get("transport", {}).get("execution_mode") != "host_mediated_external" or
                result["transport"]["request_id"] != expected["request_id"]):
            raise ValueError("actual correlated external model reply required")
        references = saved.get("call_receipts", [])
        if not references:
            raise ValueError("native reply has no accounted model invocation")
        response_paths = []
        for reference in references:
            call = read_json(root / "calls" / (reference["call_id"] + ".json"))
            if (agent_graph.digest(call) != reference["sha256"] or
                    state["calls"].get(reference["call_id"], {}).get("receipt_sha256") != reference["sha256"] or
                    call["kind"] != "model" or call["status"] != "completed" or
                    call.get("result") != result):
                raise ValueError("native model call accounting differs")
            response_paths.append(_pin(call["external_response"], root))
        request_path = root / current["external_request"]["path"]
        document = read_json(request_path)
        if (agent_graph.digest(document) != current["external_request"]["sha256"] or
                document["sha256"] != agent_graph.digest({k: v for k, v in document.items() if k != "sha256"}) or
                document["request"] != expected):
            raise ValueError("prepared native model request changed")
        return saved, root / current["result"]["path"], request_path, response_paths


def materialize_agent_candidate(config_path, packet_pin, graph_root, output_dir):
    """Copy exact model code/assets/call provenance into a new unreviewed draft.

    Original source assets are retained unchanged. Returned metadata has distinct
    candidate filenames; its correctness is an obligation for native tests.
    No previous dependency closure, build receipt or scientific vote is inherited.
    """
    loaded = _load(config_path)
    packet_path = _pin(packet_pin, loaded["path"].parent)
    panel = read_json(packet_path)
    if panel != _source_packet(loaded):
        raise ValueError("native draft packet/configuration changed")
    saved, receipt_path, request_path, response_paths = _proposal_receipt(graph_root, packet_pin)
    raw = saved["result"]["value"]
    validate_public_result(raw, output_schema(loaded["config"], loaded["capsule"]["routine"]))
    source_bytes=sum(len(raw[k].encode()) for k in ('translation_unit','metadata_info','metadata_plot'))
    source_bytes+=sum(len(row['text'].encode()) for row in raw.get('supporting_files',[]))
    if source_bytes>MAX_SOURCE_BYTES:
        raise ValueError('bounded aggregate model source bytes required')
    served, unserved = raw["served_obligations"], raw["unserved_obligations"]
    wanted = {o["id"] for o in loaded["config"]["obligations"]}
    if (len(set(served)) != len(served) or len(set(unserved)) != len(unserved) or
            set(served) & set(unserved) or set(served) | set(unserved) != wanted or
            not raw["source_claim_ids"]):
        raise ValueError("every obligation must be served or explicitly unserved")
    output = Path(output_dir).absolute()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("candidate materialization requires a fresh ordinary directory")
    output.mkdir(parents=True)
    target = raw["routine_name"]
    tree = output / "source"; tree.mkdir()
    facts = []
    def retain(relative, content, role):
        path = tree / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        facts.append({"path": relative, "sha256": sources.digest(path), "role": role})
    retain(target + ".cc", raw["translation_unit"].encode(), "compile")
    retain(target + ".info", raw["metadata_info"].encode(), "configuration")
    retain(target + ".plot", raw["metadata_plot"].encode(), "configuration")
    for row in raw.get("supporting_files", []):
        relative = sources.relative_path(row["path"])
        if (Path(relative).suffix not in (".hh", ".h") or relative in {f["path"] for f in facts}
                or relative.startswith(("original/", "provenance/"))):
            raise ValueError("distinct ordinary header support files required")
        retain(relative, row["text"].encode(), "header")
    for fact in loaded["capsule"]["files"]:
        # Original metadata/reference retain original basenames for refDataName.
        retain("original/" + fact["path"], (loaded["root"] / fact["path"]).read_bytes(),
               "data" if fact["role"] == "compile" else fact["role"])
    provenance = {"configuration.json": loaded["path"], "source-capsule.json": loaded["capsule_path"],
        "source-request.json": packet_path, "model-request.json": request_path,
        "model-receipt.json": receipt_path, "build-runtime-template.json": loaded["template_path"]}
    provenance.update({"model-response-" + str(i) + ".json": path for i, path in enumerate(response_paths)})
    if loaded.get("lineage") is not None:
        provenance["improvement-lineage.json"] = _pin(loaded["config"]["improvement_lineage"], loaded["path"].parent)
        if "continuation_campaign" in loaded["config"]:
            provenance["continuation-campaign.json"] = _pin(loaded["config"]["continuation_campaign"], loaded["path"].parent)
    for name, path in provenance.items():
        retain("provenance/" + name, path.read_bytes(), "data")
    draft = {"schema_version": 1, "kind": "analysis-source-capsule", "framework": "rivet",
        "routine": target, "source": {"repository": "supplied", "revision": None,
            "description": "Actual externally hosted model proposal; unchanged original sources and call provenance retained."},
        "root": str(tree), "files": facts,
        "layout": {"include_dirs": ["."], "asset_dirs": sorted({str(Path(f["path"]).parent) for f in facts if f["role"] in ("reference", "configuration")})},
        "dependencies": [{"name": "fresh-candidate-closure", "kind": "source", "status": "unresolved",
            "files": [target + ".cc"], "reason": "New C++/headers/assets/runtime obligations require independent fresh review."}],
        "dependency_review": {"complete": False, "description": "No original or model-declared closure is inherited; fresh independent source dependency review required."},
        "submodules": []}
    sources.validate_capsule(draft)
    bindings = sources.routine_bindings(draft, output, [target + ".cc"])
    if bindings[target]["registration"] == "declared-capsule-primary" or set(bindings) != {target}:
        raise ValueError("candidate needs its sole positively bound literal canonical registration")
    capsule_path = output / "candidate-capsule.json"; atomic_json(capsule_path, draft)
    build = deepcopy(loaded["template"])
    build["schema_version"] = 1; build.pop("execution_identity")
    build["source_capsule"] = str(capsule_path)
    build["recipe"]["compile_units"] = [target + ".cc"]
    build["recipe"]["output"] = "Rivet" + target + ".so"
    if loaded.get("lineage") is not None:
        build["improvement_lineage"] = deepcopy(loaded["config"]["improvement_lineage"])
    build["probe"] = {"executable": "probe", "arguments": ["--show-analysis", target],
        "expected_exit_code": 0, "stdout_contains": [target]}
    build_path = output / "routine-build-unreviewed.json"; atomic_json(build_path, build)
    binding = {"schema_version": 1, "kind": "actual-native-construction-draft",
        "source_capsule_sha256": sources.digest(capsule_path), "translation_unit_sha256": sources.digest(tree / (target + ".cc")),
        "source_configuration_sha256": sources.digest(loaded["path"]), "source_packet": deepcopy(packet_pin),
        "model_transport": saved["result"]["transport"], "served_obligations": served,
        "unserved_obligations": unserved, "prior_reviews_carried": [],
        "fresh_dependency_review_required": True, "fresh_runtime_seal_required": True,
        "fresh_scientific_plan_required": True, "execution_authorized": False, "physics_validated": False,
        "limitations": ["External host/model/freshness fields are attestations, not authenticated identities.",
            "Model-declared served obligations require compiler and complete native-event/output checks."]}
    if loaded.get("lineage") is not None:
        binding["improvement_lineage"] = deepcopy(loaded["config"]["improvement_lineage"])
        binding["revision_type"] = "improve_successful_native_incumbent"
        binding["retained_incumbent_result"] = loaded["lineage"]["parent_result"]
    atomic_json(output / "candidate-binding.json", binding)
    return {"capsule": str(capsule_path), "build_task": {"backend": "routine-build", "input": str(build_path)}, "binding": binding}


def validate(task):
    """Ordinary worker materializes a completed Host proposal; it never calls it."""
    _keys(task,('backend','input','source_packet','graph_root'))
    if task['backend']!='native-construction' or any(type(task[k]) is not str or not task[k].strip()
            for k in ('input','graph_root')):
        raise ValueError('explicit native construction materialization task required')
    _keys(task['source_packet'],('path','sha256'))


def inputs(task,base):
    validate(task)
    loaded=_load(regular(task['input'],base))
    packet_path=_pin(task['source_packet'],base)
    if read_json(packet_path)!=_source_packet(loaded):
        raise ValueError('ordinary materialization packet/source identity differs')
    graph=Path(task['graph_root'])
    if not graph.is_absolute():graph=Path(base)/graph
    if any(p.is_symlink() for p in (graph,*graph.parents)) or not graph.is_dir():
        raise ValueError('ordinary existing Host graph required')
    saved,receipt,request,responses=_proposal_receipt(graph,task['source_packet'])
    paths=[Path(__file__).resolve(),loaded['path'],loaded['capsule_path'],loaded['template_path'],
        packet_path,*loaded['files'],receipt,request,*responses,
        graph/agent_graph.SPEC,graph/agent_graph.STATE]
    paths += [_pin({k:f[k] for k in ('path','sha256')},loaded['path'].parent) for f in loaded['api']+loaded['support']]
    for ref in saved['call_receipts']:paths.append(graph/'calls'/(ref['call_id']+'.json'))
    if loaded['lineage'] is not None:
        from . import native_incumbent
        paths += native_incumbent.input_paths(loaded['config']['improvement_lineage'],loaded['path'].parent)
        if 'continuation_campaign' in loaded['config']:
            campaign=native_incumbent.validate_campaign(loaded['config']['continuation_campaign'],base,
                loaded['config']['improvement_lineage'])
            if graph.resolve()!=Path(campaign['graph_root']):
                raise ValueError('materialization must consume the declared continuation graph')
            paths.append(_pin(loaded['config']['continuation_campaign'],base))
            paths += [_pin(p,base) for p in campaign['historical_ledger']]
    return list(dict.fromkeys(paths))


def execution_seconds(task,base):
    inputs(task,base)
    loaded=_load(regular(task['input'],base))
    if loaded['lineage'] is not None:
        from . import native_incumbent
        return native_incumbent.execution_seconds(loaded['config']['improvement_lineage'],base,60)
    return 60


def run(task,base,out,*,worker_started=None):
    """Public science worker route after its own prospective v2 approval."""
    from ravel.physics import native_incumbent
    started=native_incumbent.worker_start(worker_started)
    paths=inputs(task,base);before={str(p):sources.digest(p) for p in paths}
    loaded=_load(regular(task['input'],base));boundary=None
    if loaded['lineage'] is not None:
        from . import native_incumbent
        boundary=native_incumbent.WorkerBoundary(loaded['config']['improvement_lineage'],base,out,
            work_seconds=60,worker_started=started)
    destination=Path(out)/'candidate'
    draft=materialize_agent_candidate(regular(task['input'],base),task['source_packet'],
        task['graph_root'],destination)
    if any(sources.digest(p)!=before[str(p)] for p in paths):
        raise ValueError('materialization changed incumbent or Host inputs')
    result={'status':'passed','kind':'native-construction-materialization',
        'scope':'Source-only materialization of a completed actual Host reply; fresh native build/event review remains required',
        'candidate_disposition':'unreviewed_source','capsule':draft['capsule'],
        'build_task':draft['build_task'],'binding':draft['binding'],
        'prior_reviews_carried':[],'model_calls':0,'native_calls':0,
        'execution_authorized':False,'physics_validated':False}
    if boundary is not None:
        result['historical_qualification']=boundary.finish()
    return result


def run_in_worker(task,base,out,*,worker_started):
    """The ordinary science worker supplies its common pre-admission clock."""
    return run(task,base,out,worker_started=worker_started)


def helper_declaration(task, base_dir, output_dir, *, _session=None):
    loaded=_load(regular(task['input'],base_dir))
    config=loaded['config']
    if 'improvement_lineage' not in config:return None
    from . import native_incumbent
    return native_incumbent.helper_declaration(config['improvement_lineage'],loaded['path'].parent,output_dir,_session=_session)
