"""Source-bound construction and feedback for finite supplied routine candidates.

This composes the existing source capsule, typed analysis IR, detached witness
and native builder. A caller or agent supplies the source interpretation and a
finite construction board. Literal byte/line binding does not establish that
the interpretation faithfully implements an arbitrary C++ analysis.
Each revised candidate is a separate prospective scientific study.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from ravel import analysis_sources as sources
from ravel.physics import analysis_ir, routine_build
from ravel.validation import analysis_witness
from ravel.workflow.state_io import atomic_json

MAX_DOCUMENT_BYTES = 4_000_000
CLAIM_KINDS = {"objects", "expression", "selection", "ordering", "output", "normalization"}
TRIGGERS = {"typed_compiler", "native_compiler", "event_selection", "source_interpretation"}


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError("invalid " + label + " fields")


def _name(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("bounded candidate/claim identity required")
    return value


def _sha(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("exact SHA256 required")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _repair_witness_atoms(witness):
    """Observed output/membership obligations, never inferred causal faults."""
    atoms = {("output", _name(row["node"]))
             for row in witness["source_output_differences"]}
    changed_regions = set(witness["left_regions"]) ^ set(witness["right_regions"])
    atoms.update(("membership", _name(name)) for name in changed_regions)
    if witness["selection_changed"] and not changed_regions:
        atoms.add(("selection_interface",))
    return atoms


def _select_repair_witnesses(differences, events):
    """Cover observed obligations within the old four-event context allowance.

    This deterministic greedy heuristic grants no correctness or fault-class
    claim. It never exposes more events or serialized witness/event bytes than
    the previous prefix. Complete oracle evidence remains outside this helper.
    """
    by_id = {row["event_id"]: row for row in events}
    if len(by_id) != len(events):
        raise ValueError("repair context requires unique original event IDs")
    def size(value):
        return len(json.dumps(value, sort_keys=True, allow_nan=False).encode())
    candidates = []
    seen = set()
    for witness in differences:
        identity = witness["event_id"]
        if identity in seen or identity not in by_id:
            raise ValueError("repair witness adds or duplicates original event IDs")
        seen.add(identity)
        event = by_id[identity]
        if witness["input_event_sha256"] != _digest(event):
            raise ValueError("repair witness original event bytes differ")
        candidates.append({"witness": witness, "atoms": _repair_witness_atoms(witness),
                           "bytes": size(witness) + size(event)})
    prefix = candidates[:4]
    # Exact JSON size of {events: [...], witnesses: [...]}, including both
    # lists' comma-space separators. Addition avoids repeatedly encoding events.
    empty_size = size({"events": [], "witnesses": []})
    def context_size(rows):
        return empty_size + sum(row["bytes"] for row in rows) + 4 * max(0, len(rows) - 1)
    allowance = context_size(prefix)
    selected, covered = [], set()
    while len(selected) < 4:
        available = [row for row in candidates
                     if row["atoms"] - covered and context_size(selected + [row]) <= allowance]
        if not available:
            break
        chosen = min(available, key=lambda row: (
            -len(row["atoms"] - covered), row["bytes"],
            row["witness"]["input_event_sha256"], row["witness"]["event_id"]))
        selected.append(chosen)
        covered.update(chosen["atoms"])
        candidates.remove(chosen)
    # Greedy set cover is not optimal. Never sacrifice the observable coverage
    # already available in the budget-feasible original prefix.
    prefix_atoms = set().union(*(row["atoms"] for row in prefix))
    if len(covered) < len(prefix_atoms):
        selected = prefix
    return deepcopy([row["witness"] for row in sorted(selected, key=lambda row: (
        row["witness"]["input_event_sha256"], row["witness"]["event_id"]))])


def _case_content_digests(events):
    """Compare supplied case contents independently of event/group labels.

    Reassigning labels, order or grouping cannot turn development cases into a
    held-out population. This establishes input novelty, not statistical
    independence or that the proposer never saw the supplied contents.
    """
    def quantity(value):
        # These supplied IR quantities are read as binary64. JSON 1/1.0 and
        # 0/-0 are the same case; exact integer charge/ID flags stay integers.
        return 0.0 if value == 0 else float(value)
    result = set()
    for row in events:
        content = deepcopy({key: row[key] for key in ("weights", "objects", "met")})
        content["weights"] = {key: quantity(value) for key, value in content["weights"].items()}
        for objects in content["objects"].values():
            for obj in objects:
                for key in ("pt", "eta", "phi", "mass"):
                    obj[key] = quantity(obj[key])
        content["met"] = {key: quantity(value) for key, value in content["met"].items()}
        result.add(_digest(content))
    return result


def _regular(value, base):
    from ravel.workflow.science import regular
    return regular(value, base)


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("construction document exceeds byte bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON value")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject)
    # Exponent overflow is not caught by parse_constant.
    json.dumps(result, allow_nan=False)
    return result


def _pin(fact, base):
    _keys(fact, ("path", "sha256"), "input pin")
    _sha(fact["sha256"])
    path = _regular(fact["path"], base)
    if sources.digest(path) != fact["sha256"]:
        raise ValueError("construction input bytes differ: " + str(path))
    return path


def _ids(values, available):
    if (type(values) is not list or not values or len(values) > 256
            or any(type(v) is not str for v in values) or len(set(values)) != len(values)
            or set(values) - set(available)):
        raise ValueError("nonempty unique bound source claims required")
    return values


def validate(task):
    _keys(task, ("backend", "input", "candidate", "parent_feedback"), "routine construction task")
    if task["backend"] != "routine-candidate" or type(task["input"]) is not str or not task["input"]:
        raise ValueError("routine-candidate requires explicit construction input")
    _name(task["candidate"])
    if task["parent_feedback"] is not None:
        _keys(task["parent_feedback"], ("path", "sha256"), "parent feedback")
        _sha(task["parent_feedback"]["sha256"])


def construct(recipe, claims):
    """Actually assemble a typed program from source-linked construction steps.

    The typed compiler runs later so an approved erroneous draft can produce
    retained compiler feedback. It never executes arbitrary recipe code.
    """
    _keys(recipe, ("schema_version", "name", "steps", "regions", "limits"), "construction recipe")
    if type(recipe["schema_version"]) is not int or recipe["schema_version"] != 1:
        raise ValueError("unsupported construction recipe version")
    _name(recipe["name"])
    if type(recipe["steps"]) is not list or not 1 <= len(recipe["steps"]) <= 256:
        raise ValueError("bounded construction steps required")
    nodes, bindings = [], []
    for step in recipe["steps"]:
        _keys(step, ("node", "claims"), "construction step")
        if type(step["node"]) is not dict:
            raise ValueError("construction node must be an object")
        _name(step["node"].get("id"))
        _ids(step["claims"], claims)
        nodes.append(deepcopy(step["node"]))
        bindings.append({"node": step["node"]["id"], "claims": deepcopy(step["claims"])})
    if type(recipe["regions"]) is not list or not 1 <= len(recipe["regions"]) <= 128:
        raise ValueError("bounded constructed regions required")
    regions = []
    for entry in recipe["regions"]:
        _keys(entry, ("region", "claims"), "constructed region")
        _ids(entry["claims"], claims)
        regions.append(deepcopy(entry["region"]))
    return {"schema_version": 1, "name": recipe["name"], "nodes": nodes,
            "regions": regions, "limits": deepcopy(recipe["limits"])}, bindings


def _load(task, base):
    validate(task)
    config_path = _regular(task["input"], base)
    base = config_path.parent
    config = _read(config_path)
    fields = ("schema_version", "kind", "source_capsule", "source_scope", "claims", "contract", "events", "event_domain", "model_construction", "population_review",
              "reference", "repair_board", "candidates")
    if "improvement_lineage" in config:
        fields += ("improvement_lineage",)
    _keys(config, fields, "construction configuration")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1 or config["kind"] != "routine-construction":
        raise ValueError("unsupported routine construction configuration")
    source_path = _pin(config["source_capsule"], base)
    capsule = sources.load_capsule(source_path)
    original = sources.inventory(capsule, source_path.parent)
    scope = config["source_scope"]
    _keys(scope, ("kind", "unserved_obligations"), "construction source scope")
    if (scope["kind"] not in ("supplied_object_port", "complete_routine")
            or type(scope["unserved_obligations"]) is not list
            or any(type(v) is not str or not v.strip() for v in scope["unserved_obligations"])
            or len(scope["unserved_obligations"]) > 64):
        raise ValueError("explicit bounded source scope and unserved obligations required")
    unresolved = not original["dependency_review"]["complete"] or any(d["status"] != "resolved" for d in original["dependencies"])
    if unresolved and (scope["kind"] != "supplied_object_port" or not scope["unserved_obligations"]):
        raise ValueError("unresolved source dependency obligations require a limited supplied-object port with unserved obligations")
    if scope["kind"] == "complete_routine" and scope["unserved_obligations"]:
        raise ValueError("complete routine cannot have unserved obligations")
    source_root, source_files = sources.source_files(capsule, source_path.parent)
    files = [config_path, source_path, *source_files]
    if type(config["claims"]) is not list or not 1 <= len(config["claims"]) <= 256:
        raise ValueError("bounded source claim ledger required")
    claims = {}
    declared = {fact["path"] for fact in capsule["files"]}
    for claim in config["claims"]:
        _keys(claim, ("id", "path", "line_start", "line_end", "excerpt_sha256", "kind"), "source claim")
        cid = _name(claim["id"])
        if cid in claims or claim["path"] not in declared or claim["kind"] not in CLAIM_KINDS:
            raise ValueError("duplicate/unbound source claim or unsupported claim kind")
        start, end = claim["line_start"], claim["line_end"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= start + 199:
            raise ValueError("source claim needs an exact bounded line span")
        raw_lines = (source_root / claim["path"]).read_bytes().splitlines(keepends=True)
        if end > len(raw_lines):
            raise ValueError("source claim line span exceeds source")
        excerpt = b"".join(raw_lines[start - 1:end])
        excerpt.decode("utf-8")
        if hashlib.sha256(excerpt).hexdigest() != _sha(claim["excerpt_sha256"]):
            raise ValueError("source claim excerpt differs")
        claims[cid] = claim
    contract_path, events_path = [_pin(config[k], base) for k in ("contract", "events")]
    files.extend((contract_path, events_path))
    contract, events = _read(contract_path), _read(events_path)
    domain_path = _pin(config["event_domain"], base)
    domain = _read(domain_path)
    _keys(domain, ("schema_version", "kind", "jet_mass", "interpretation"), "supplied event domain")
    if (type(domain["schema_version"]) is not int or domain["schema_version"] != 1
            or domain["kind"] != "supplied-reconstructed-domain"
            or domain["jet_mass"] not in ("massless", "supplied_nonnegative")
            or type(domain["interpretation"]) is not str or not domain["interpretation"].strip()):
        raise ValueError("explicit supported supplied-object domain required")
    if type(events) is not list or not events:
        raise ValueError("nonempty complete supplied event population required")
    if domain["jet_mass"] == "massless":
        for event in events:
            for jet in event["objects"]["jet"]:
                if type(jet["mass"]) not in (int, float) or jet["mass"] != 0:
                    raise ValueError("massless-jet interpretation does not admit a massive supplied jet")
    files.append(domain_path)
    for evidence in contract.get("response_evidence", []):
        files.append(_regular(evidence, base))
    ref = config["reference"]
    _keys(ref, ("kind", "bundle", "manifest_sha256", "source_capsule_sha256", "claims", "interpretation", "source_oracle"), "reference witness")
    if (ref["kind"] != "detached-analysis-witness" or ref["source_capsule_sha256"] != sources.digest(source_path)
            or type(ref["interpretation"]) is not str or not ref["interpretation"].strip()):
        raise ValueError("reference needs explicit original-source interpretation and custody")
    _ids(ref["claims"], claims)
    ref_manifest = _regular(str(Path(ref["bundle"]) / "manifest.json"), base)
    if sources.digest(ref_manifest) != _sha(ref["manifest_sha256"]):
        raise ValueError("reference manifest differs")
    ref_bundle = ref_manifest.parent
    verification = analysis_witness.verify_bundle(ref_bundle, ref["manifest_sha256"])
    if not verification["passed"]:
        raise ValueError("reference detached witness refused: " + verification["error"])
    manifest = _read(ref_manifest)
    files.extend([ref_manifest, *[ref_bundle / name for name in manifest["files"]]])
    upstream_events, upstream_contract = [_read(ref_bundle / name) for name in ("events.json", "contract.json")]
    if events != upstream_events or contract != upstream_contract:
        raise ValueError("complete upstream event population/content/object contract differs")
    oracle_path = _pin(ref["source_oracle"], base)
    oracle = _read(oracle_path)
    _verify_source_oracle(oracle, _reference_result(ref_bundle), sources.digest(source_path), sources.digest(events_path))
    files.append(oracle_path)
    population = None
    if config["population_review"] is not None:
        ledger_path = _pin(config["population_review"], base)
        ledger = _read(ledger_path)
        _keys(ledger, ("source_seed", "raw_case_population", "admitted_port_population",
            "explicit_domain_refusal_population", "refused_cases", "scope_exceptions",
            "all_cases_preserved", "physics_validated"), "original population review")
        seed_path = _pin(ledger["source_seed"], base)
        seed = _read(seed_path)
        seed_source = _pin({key: seed["source"][key] for key in ("path", "sha256")}, seed_path.parent)
        if seed_source not in source_files:
            raise ValueError("original population seed source is outside the bound capsule")
        population = _verify_population(ledger, seed, events, oracle, domain)
        files.extend((ledger_path, seed_path, seed_source))
    candidates = config["candidates"]
    if type(candidates) is not list or not 1 <= len(candidates) <= 8:
        raise ValueError("one to eight finite candidates required")
    by_id = {}
    for candidate in candidates:
        _keys(candidate, ("id", "parent", "recipe", "candidate_source_capsule", "build", "reason"), "candidate")
        cid = _name(candidate["id"])
        if cid in by_id or type(candidate["reason"]) is not str or not candidate["reason"].strip():
            raise ValueError("duplicate candidate or missing construction reason")
        construct(candidate["recipe"], claims)
        csp = _pin(candidate["candidate_source_capsule"], base)
        cc = sources.load_capsule(csp)
        ci = sources.inventory(cc, csp.parent)
        if candidate["build"] is not None and (not ci["dependency_review"]["complete"] or any(d["status"] != "resolved" for d in ci["dependencies"])):
            raise ValueError("candidate dependencies unresolved")
        _, cfiles = sources.source_files(cc, csp.parent)
        files.extend([csp, *cfiles])
        if candidate["build"] is not None:
            bp = _pin(candidate["build"], base)
            build_config = _read(bp)
            if build_config.get("schema_version") != 2:
                raise ValueError("native candidate build requires prospectively sealed v2 configuration")
            actual_csp = _regular(build_config.get("source_capsule"), bp.parent)
            if actual_csp != csp:
                raise ValueError("native build differs from candidate source capsule")
            files.extend(routine_build.inputs({"backend": "routine-build", "input": str(bp)}, bp.parent))
        by_id[cid] = candidate
    if task["candidate"] not in by_id:
        raise ValueError("candidate absent from frozen finite board")
    board = config["repair_board"]
    if type(board) is not list or len(board) > 16:
        raise ValueError("bounded prospective repair board required")
    pairs = set()
    for edge in board:
        _keys(edge, ("from", "to", "claims", "trigger"), "finite repair")
        _ids(edge["claims"], claims)
        pair = edge["from"], edge["to"]
        if (pair in pairs or any(c not in by_id for c in pair) or pair[0] == pair[1]
                or edge["trigger"] not in TRIGGERS or by_id[pair[1]]["parent"] != pair[0]):
            raise ValueError("invalid or duplicate prospective repair edge")
        pairs.add(pair)
    for cid, candidate in by_id.items():
        parent = candidate["parent"]
        if parent is not None and (parent, cid) not in pairs:
            raise ValueError("revised candidate lacks a prospective repair edge")
        seen, current = set(), cid
        while current is not None:
            if current in seen or current not in by_id:
                raise ValueError("candidate parent cycle or missing parent")
            seen.add(current)
            current = by_id[current]["parent"]
    selected = by_id[task["candidate"]]
    improvement = config.get("improvement_lineage")
    if improvement is not None:
        if selected["parent"] is not None or task["parent_feedback"] is not None:
            raise ValueError("successful-incumbent improvement is separate from failed-parent repair")
        from .routine_evolution import validate_lineage
        lineage, lineage_files = validate_lineage(improvement, base)
        if lineage["incumbent_task"]["candidate"] == selected["id"]:
            raise ValueError("improvement challenger needs a fresh candidate identity")
        previous = _read(_pin(lineage["incumbent_configuration"], base))
        prior_events = _read(_pin(previous["events"], Path(lineage["incumbent_configuration"]["path"]).parent))
        if ({row["event_id"] for row in prior_events} & {row["event_id"] for row in events}
                or _case_content_digests(prior_events) & _case_content_digests(events)):
            raise ValueError("successful-incumbent challenger needs a fresh held-out case population")
        files.extend(lineage_files)
    model_construction = config["model_construction"]
    if model_construction is not None:
        _keys(model_construction, ("receipt", "request", "source_panel"), "actual model construction")
        rp, qp, pp = [_pin(model_construction[k], base) for k in ("receipt", "request", "source_panel")]
        result_receipt, request_record, panel = [_read(p) for p in (rp, qp, pp)]
        if (result_receipt.get("request") != request_record.get("request")
                or result_receipt.get("result_sha256") != _digest(result_receipt.get("result"))
                or request_record.get("sha256") != _digest({k:v for k,v in request_record.items() if k != "sha256"})
                or panel.get("source_capsule_sha256") != sources.digest(source_path)):
            raise ValueError("actual model construction request/receipt/source differs")
        request_inputs = result_receipt["request"]["input_artifacts"]
        if not any(p["path"] == str(pp) and p["sha256"] == sources.digest(pp) for p in request_inputs):
            raise ValueError("model source panel absent from actual invocation")
        raw = result_receipt["result"]["value"]
        from ravel.workflow.agent_host import validate_public_result
        validate_public_result(raw, construction_output_schema(claims))
        model_recipe = {"schema_version":1,"name":raw["name"],
            "steps":[{"node":{k:v for k,v in step["node"].items() if v is not None},"claims":step["claims"]} for step in raw["steps"]],
            "regions":raw["regions"],"limits":panel["fixed_limits"]}
        if selected["recipe"] != model_recipe:
            raise ValueError("candidate recipe differs from actual model construction reply")
        files.extend((rp, qp, pp))
    parent_feedback = None
    if selected["parent"] is None:
        if task["parent_feedback"] is not None:
            raise ValueError("initial candidate cannot inherit feedback/votes")
    else:
        if task["parent_feedback"] is None:
            raise ValueError("revision requires exact retained parent feedback")
        fp = _pin(task["parent_feedback"], base)
        files.append(fp)
        parent_feedback = _read(fp)
        if (parent_feedback.get("kind") != "routine-construction-feedback"
                or parent_feedback.get("candidate_id") != selected["parent"]
                or parent_feedback.get("construction_input_sha256") != sources.digest(config_path)
                or parent_feedback.get("candidate_disposition") == "verified_on_supplied_events"
                or parent_feedback.get("prior_reviews_carried") != []
                or parent_feedback.get("requires_fresh_prospective_review") is not True
                or task["candidate"] not in parent_feedback.get("permitted_successors", [])):
            raise ValueError("parent feedback does not admit this finite successor")
        _sha(parent_feedback.get("source_admission_id"))
        trigger = parent_feedback.get("failure_trigger")
        if not any(edge["from"] == selected["parent"] and edge["to"] == task["candidate"]
                   and edge["trigger"] == trigger for edge in board):
            raise ValueError("feedback trigger differs from prospective repair edge")
        # Rebind the actual parent delivery, not merely an asserted label in a
        # coherently rehashed JSON report. The acyclic <=8-candidate board bounds
        # this read-only ancestry check. No compiler or transport is launched.
        parent_task_path = _regular(fp.parent / "candidate-task.json", base)
        if sources.digest(parent_task_path) != _sha(parent_feedback.get("task_sha256")):
            raise ValueError("parent task custody differs")
        parent_task = _read(parent_task_path)
        if parent_task.get("candidate") != selected["parent"]:
            raise ValueError("retained parent task candidate differs")
        verify_delivery(parent_task, base, fp.parent)
        files.extend([parent_task_path, fp.parent / "candidate-source-admission.json",
                      fp.parent / "constructed-program.json", fp.parent / "source-claim-bindings.json"])
        if parent_feedback["candidate_disposition"] in ("event_mismatch", "verified_on_supplied_events"):
            files.extend([fp.parent / "standalone-verifier.json", fp.parent / "upstream-comparison.json",
                          fp.parent / "candidate-witness/manifest.json"])
            parent_manifest = _read(fp.parent / "candidate-witness/manifest.json")
            files.extend(fp.parent / "candidate-witness" / name for name in parent_manifest["files"])
        if parent_feedback["feedback"].get("native_build", {}).get("logs"):
            files.extend(_regular(log["path"], fp.parent) for log in parent_feedback["feedback"]["native_build"]["logs"])
    return {"config": config, "config_path": config_path, "base": base, "selected": selected,
            "claims": claims, "original": original, "contract": contract, "events": events,
            "reference_bundle": ref_bundle, "reference_verification": verification,
            "parent_feedback": parent_feedback, "population_review": population,
            "files": list(dict.fromkeys(files))}


def inputs(task, base_dir):
    """Read-only source admission; an invalid draft is compiled only by run."""
    return _load(task, base_dir)["files"]


def execution_seconds(task, base_dir):
    """Expose the full bounded selected branch for outer science admission.

    Existing builder has 120s per compiler-version/build/probe subprocess;
    detached replay has 30s. Reserve a further 30s for bounded IR/file work.
    This is a ceiling, not expected runtime, and grants no native job approval.
    """
    loaded = _load(task, base_dir)
    selected = loaded["selected"]
    if selected["build"] is None:
        return 60
    bp = _pin(selected["build"], loaded["base"])
    plan = routine_build.build_plan({"backend": "routine-build", "input": str(bp)}, bp.parent,
                                   loaded["base"] / ".unexecuted-budget-plan")
    return 60 + 120 * (2 + len(plan["commands"]))


def _input_pins(files):
    return [{"path": str(p), "sha256": sources.digest(p)} for p in files]


def _admission(loaded, task):
    selected = loaded["selected"]
    bound = {"construction_input_sha256": sources.digest(loaded["config_path"]),
             "candidate_id": selected["id"], "recipe_sha256": _digest(selected["recipe"]),
             "candidate_source_capsule_sha256": selected["candidate_source_capsule"]["sha256"],
             "source_claims_sha256": _digest(loaded["config"]["claims"]),
             "source_scope_sha256": _digest(loaded["config"]["source_scope"]),
             "model_construction_sha256": _digest(loaded["config"]["model_construction"]),
             "original_source_capsule_sha256": loaded["config"]["source_capsule"]["sha256"],
             "contract_sha256": loaded["config"]["contract"]["sha256"],
             "events_sha256": loaded["config"]["events"]["sha256"],
             "event_domain_sha256": loaded["config"]["event_domain"]["sha256"],
             "population_review_sha256": None if loaded["config"]["population_review"] is None else loaded["config"]["population_review"]["sha256"],
             "reference_manifest_sha256": loaded["config"]["reference"]["manifest_sha256"],
             "source_oracle_sha256": loaded["config"]["reference"]["source_oracle"]["sha256"],
             "build_sha256": None if selected["build"] is None else selected["build"]["sha256"],
             "parent_feedback_sha256": None if task["parent_feedback"] is None else task["parent_feedback"]["sha256"],
             "implementation_sources": {m.__name__: sources.digest(m.__file__) for m in
                (sources, analysis_ir, analysis_witness, routine_build)},
             "construction_implementation_sha256": sources.digest(__file__)}
    if loaded["config"].get("improvement_lineage") is not None:
        bound["improvement_lineage_sha256"] = loaded["config"]["improvement_lineage"]["sha256"]
        from . import routine_evolution
        bound["improvement_implementation_sha256"] = sources.digest(routine_evolution.__file__)
    return {"schema_version": 1, "kind": "routine-candidate-source-admission",
            "source_admission_id": _digest(bound), "bindings": bound,
            "prior_reviews_carried": [], "requires_fresh_prospective_review": True,
            "compute_authorized": False, "physics_validated": False}


def _verify_population(ledger, seed, events, oracle, domain):
    """Rebind original source cases, conversions, refusals and explicit exceptions.

    Expected physics remains an external source assertion. This establishes
    custody of the complete original denominator and the declared conversion;
    it does not turn a source author into an independent physical oracle.
    """
    if (type(seed.get("schema_version")) is not int or seed.get("schema_version") != 1 or seed.get("kind") != "independent-source-construction-witness-seed"
            or seed.get("complete_population") is not True or type(seed.get("events")) is not list
            or not seed["events"] or ledger["all_cases_preserved"] is not True
            or ledger["physics_validated"] is not False):
        raise ValueError("complete original source-case seed and explicit population scope required")
    raw = seed["events"]
    names = [row["id"] for row in raw]
    if len(names) != len(set(names)):
        raise ValueError("duplicate original population identity")
    accepted = [row for row in raw if row["expected"]["port_admission"] == "accepted"]
    refused = [row for row in raw if row["expected"]["port_admission"] != "accepted"]
    counts = (len(raw), len(accepted), len(refused))
    if (tuple(ledger[key] for key in ("raw_case_population", "admitted_port_population", "explicit_domain_refusal_population")) != counts
            or any(type(ledger[key]) is not int for key in ("raw_case_population", "admitted_port_population", "explicit_domain_refusal_population"))
            or ledger["refused_cases"] != refused):
        raise ValueError("original population/refusal denominator differs")
    for row in refused:
        if (row["expected"]["port_admission"] != "refused_massive_jet" or domain["jet_mass"] != "massless"
                or not any(jet["mass"] != 0 for jet in row["objects"]["jets"])):
            raise ValueError("original population refusal lacks a declared supported domain reason")
    converted = [{"event_id": row["id"], "group_id": row["id"], "weights": {"nominal": row["weight"]},
        "objects": {"electron": [], "muon": [], "jet": [{key: jet[key] for key in ("pt", "eta", "phi", "mass")}
            | {"charge": 0, "idbits": 0} for jet in row["objects"]["jets"]]}, "met": {"pt": 0, "phi": 0}}
        for row in accepted]
    if events != converted:
        raise ValueError("admitted event bytes/weights/objects differ from complete original seed conversion")
    expectations = {row["event_id"]: row["observables"] for row in oracle["records"]}
    exceptions = ledger["scope_exceptions"]
    if type(exceptions) is not list or len(exceptions) > len(accepted):
        raise ValueError("bounded explicit population exceptions required")
    excepted = set()
    for exception in exceptions:
        _keys(exception, ("event_id", "unserved_output", "reason"), "population scope exception")
        name = exception["event_id"]
        if (name in excepted or name not in expectations or exception["unserved_output"] != "exact_equal_pT_tie_order"
                or type(exception["reason"]) is not str or not exception["reason"].strip()):
            raise ValueError("unsupported or duplicate original population scope exception")
        row = next(row for row in accepted if row["id"] == name)
        by_id = {jet["id"]: jet for jet in row["objects"]["jets"]}
        selected = [by_id[identity] for identity in row["expected"]["ordered_accepted_jets"]]
        if (len({jet["pt"] for jet in selected}) == len(selected) or "ordered_jets" in expectations[name]):
            raise ValueError("tie exception must preserve original equal-pT seed and explicit order omission")
        excepted.add(name)
    for row in accepted:
        name = row["id"]
        observed = expectations[name]
        if "ordered_jets" not in observed and name not in excepted:
            raise ValueError("original population silently omits an ordering assertion")
        # Scalars directly named by the independent author remain literal.
        for key in ("n_good", "HT_TeV", "HT2_GeV", "ystar", "mjj_GeV"):
            if key in row["expected"] and observed.get(key) != row["expected"][key]:
                raise ValueError("original population source scalar assertion differs")
    return {"raw_case_population": counts[0], "admitted_port_population": counts[1],
        "explicit_domain_refusal_population": counts[2], "original_event_ids": names,
        "refused_event_ids": [row["id"] for row in refused], "scope_exceptions": deepcopy(exceptions),
        "source_assertions_authenticated": False, "physics_validated": False}


def _reference_result(bundle):
    result = _read(bundle / "result.json")
    result["inputs"] = {k: _read(bundle / (k + ".json")) for k in ("program", "contract", "events")}
    result["decisions"] = _read(bundle / "trace.json")
    return result


def _verify_source_oracle(oracle, result, source_sha, events_sha):
    """Check every event against an externally supplied source-case oracle.

    Numerical replay and source interpretation are separate. This catches a
    self-consistent but incorrectly interpreted baseline on the supplied cases;
    an oracle author's scientific authority is not authenticated by its hash.
    """
    _keys(oracle, ("schema_version", "kind", "source_capsule_sha256", "events_sha256", "records", "author", "scope"), "source-case oracle")
    if (type(oracle["schema_version"]) is not int or oracle["schema_version"] != 1
            or oracle["kind"] != "source-case-oracle" or oracle["source_capsule_sha256"] != source_sha
            or oracle["events_sha256"] != events_sha or type(oracle["author"]) is not str
            or not oracle["author"].strip() or type(oracle["scope"]) is not str or not oracle["scope"].strip()
            or type(oracle["records"]) is not list):
        raise ValueError("source oracle identity/domain differs")
    by_id = {}
    for row in oracle["records"]:
        _keys(row, ("event_id", "regions", "observables"), "source oracle event")
        if row["event_id"] in by_id or type(row["observables"]) is not dict:
            raise ValueError("duplicate or malformed source oracle event")
        by_id[row["event_id"]] = row
    if set(by_id) != {row["event_id"] for row in result["decisions"]}:
        raise ValueError("source oracle omits or adds original events")
    for actual in result["decisions"]:
        expected = by_id[actual["event_id"]]
        if actual["regions"] != expected["regions"]:
            raise ValueError("source oracle selection differs: " + actual["event_id"])
        for name, value in expected["observables"].items():
            if name not in actual["nodes"]:
                raise ValueError("source oracle names unknown expression: " + name)
            measured = actual["nodes"][name]["value"]
            if type(value) in (int, float) and type(measured) in (int, float):
                agrees = math.isfinite(value) and math.isclose(value, measured, abs_tol=1e-10, rel_tol=1e-10)
            else:
                agrees = type(value) is type(measured) and value == measured
            if not agrees:
                raise ValueError("source oracle expression differs: " + actual["event_id"] + "/" + name)
    return {"status": "passed", "events": len(by_id), "source_interpretation": "externally asserted case oracle only"}


def _compare_reference(loaded, actual):
    """Compare named source outputs without demanding identical model topology.

    Each program's entire trace is independently replayed. Cross-program
    comparison checks the complete population, source-oracle output interface
    and memberships; differently decomposed internal expressions are permitted.
    """
    reference = _reference_result(loaded["reference_bundle"])
    if actual["inputs"]["events"] != reference["inputs"]["events"] or actual["inputs"]["contract"] != reference["inputs"]["contract"]:
        raise ValueError("complete upstream event content or contract differs")
    expected_regions = set(reference["region_names"])
    oracle = _read(_pin(loaded["config"]["reference"]["source_oracle"], loaded["base"]))
    expected = {row["event_id"]: row for row in oracle["records"]}
    rows = {row["event_id"]: row for row in actual["decisions"]}
    if len(rows) != len(actual["decisions"]) or set(rows) != set(expected):
        raise ValueError("differential comparison requires the unique complete original population")
    witnesses, counts = [], {"numerical_only": 0, "predicate_only": 0, "selection_changed": 0}
    interface_differs = set(actual["region_names"]) != expected_regions
    for event in actual["inputs"]["events"]:
        row, target = rows[event["event_id"]], expected[event["event_id"]]
        differing = []
        for name, value in target["observables"].items():
            measured = row["nodes"].get(name, {}).get("value", "absent_required_output")
            if type(value) in (int, float) and type(measured) in (int, float):
                agrees = math.isfinite(value) and math.isclose(value, measured, abs_tol=1e-10, rel_tol=1e-10)
            else:
                agrees = type(value) is type(measured) and value == measured
            if not agrees:
                differing.append({"node": name, "expected": value, "actual": measured})
        selection = interface_differs or set(row["regions"]) != set(target["regions"])
        if differing or selection:
            category = "selection_changed" if selection else "numerical_only"
            counts[category] += 1
            witnesses.append({"event_id": event["event_id"], "first_divergent_node": differing[0]["node"] if differing else None,
                "source_output_differences": differing, "selection_changed": selection, "change_kind": category,
                "left_regions": target["regions"], "right_regions": row["regions"],
                "input_event_sha256": _digest(event), "object_lineage": row["object_lineage"]})
    return {"status": "failed" if witnesses else "passed", "events": len(rows), "matched_events": len(rows)-len(witnesses),
        "change_counts": counts, "witnesses": witnesses, "physics_validated": False,
        "scope": "Complete supplied event population, externally source-asserted named outputs and membership; internal topology may differ"}


def _detached_check(bundle):
    checksum = sources.digest(bundle / "manifest.json")
    environment = {"PATH": os.defpath, "LC_ALL": "C", "PYTHONUTF8": "1", "PYTHONCOERCECLOCALE": "0",
                   "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    command = [sys.executable, "-I", str(bundle / "verify.py"), "--bundle", str(bundle),
               "--manifest-sha256", checksum]
    process = subprocess.run(command, env=environment, cwd=bundle, capture_output=True, text=True, timeout=30)
    report = json.loads(process.stdout)
    if process.returncode != 0 or not report.get("passed") or report.get("manifest_sha256") != checksum:
        raise ValueError("fresh standalone candidate verifier failed")
    return {"command": command, "environment": environment, "returncode": process.returncode,
            "python_sha256": sources.digest(Path(sys.executable).resolve()),
            "checker_sha256": sources.digest(bundle / "verify.py"), "report": report}


def run(task, base_dir, outdir):
    loaded = _load(task, base_dir)
    before = _input_pins(loaded["files"])
    out = Path(outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "candidate-source-admission.json").exists():
        raise ValueError("candidate output already exists; use a fresh admitted study")
    admission = _admission(loaded, task)
    atomic_json(out / "candidate-source-admission.json", admission)
    normalized_task = {**task, "input": str(loaded["config_path"]),
                       "parent_feedback": None if task["parent_feedback"] is None else
                       {"path": str(_pin(task["parent_feedback"], loaded["base"])),
                        "sha256": task["parent_feedback"]["sha256"]}}
    atomic_json(out / "candidate-task.json", normalized_task)
    program, bindings = construct(loaded["selected"]["recipe"], loaded["claims"])
    atomic_json(out / "constructed-program.json", program)
    atomic_json(out / "source-claim-bindings.json", {"claims": list(loaded["claims"].values()),
                "bindings": bindings, "semantic_fidelity": "external interpretation requires independent scientific review"})
    feedback = {"schema_version": 1, "kind": "routine-construction-feedback", "status": "passed",
                "candidate_id": task["candidate"], "source_admission_id": admission["source_admission_id"],
                "construction_input_sha256": sources.digest(loaded["config_path"]),
                "task_sha256": sources.digest(out / "candidate-task.json"),
                "prior_reviews_carried": [], "requires_fresh_prospective_review": True,
                "candidate_disposition": None, "failure_trigger": None, "permitted_successors": [],
                "physics_validated": False, "execution_authorized": False, "feedback": {},
                "scope": "Construction and diagnostic feedback on supplied source interpretation and full event population"}
    feedback["source_scope"] = deepcopy(loaded["config"]["source_scope"])
    feedback["source_dependency_review"] = deepcopy(loaded["original"]["dependency_review"])
    feedback["population_review"] = deepcopy(loaded["population_review"])
    try:
        compiled = analysis_ir.compile_program(program, loaded["contract"])
        atomic_json(out / "typed-compiler.json", {"status": "passed", "compiled_plan": compiled})
    except ValueError as exc:
        feedback.update(candidate_disposition="typed_compiler_refused", failure_trigger="typed_compiler")
        feedback["feedback"]["typed_compiler"] = {"status": "refused", "error": str(exc)}
    if feedback["candidate_disposition"] is None and loaded["selected"]["build"] is not None:
        bp = _pin(loaded["selected"]["build"], loaded["base"])
        build_task = {"backend": "routine-build", "input": str(bp)}
        build_out = out / "native-build"
        try:
            receipt = routine_build.run(build_task, bp.parent, build_out)
            plan = _read(build_out / "build-plan.json")
            routine_build.verify_receipt(receipt, plan, bp.parent, build_out)
            feedback["feedback"]["native_build"] = {"status": "passed", "receipt_sha256": sources.digest(build_out / "build-receipt.json"),
                "scope": "Native compilation/load probe only; candidate event replay below executes typed IR, not this binary."}
        except ValueError as exc:
            # Only a retained actual compiler nonzero return is a repair trigger.
            logs = []
            for path in sorted(build_out.glob("build-*.log")):
                log = _read(path)
                logs.append({"path": str(path.relative_to(out)), "sha256": sources.digest(path),
                             "returncode": log["returncode"], "command": log["command"]})
            failed_compile = any(log["returncode"] != 0 for log in logs)
            feedback.update(candidate_disposition="native_build_refused",
                            failure_trigger="native_compiler" if failed_compile else None)
            feedback["feedback"]["native_build"] = {"status": "refused", "error": str(exc), "logs": logs}
    if feedback["candidate_disposition"] is None:
        result = analysis_ir.evaluate_program(program, loaded["contract"], loaded["events"])
        analysis_ir.write_bundle(result, out / "candidate-witness")
        detached = _detached_check(out / "candidate-witness")
        atomic_json(out / "standalone-verifier.json", detached)
        comparison = _compare_reference(loaded, result)
        atomic_json(out / "upstream-comparison.json", comparison)
        feedback["feedback"].update(independent_verification=detached["report"], upstream_comparison=comparison)
        feedback.update(candidate_disposition="verified_on_supplied_events" if comparison["status"] == "passed" else "event_mismatch",
                        failure_trigger=None if comparison["status"] == "passed" else "event_selection")
    if feedback["failure_trigger"] is not None:
        feedback["permitted_successors"] = [edge["to"] for edge in loaded["config"]["repair_board"]
            if edge["from"] == task["candidate"] and edge["trigger"] == feedback["failure_trigger"]]
    after = _input_pins(_load(task, base_dir)["files"])
    if before != after:
        raise ValueError("construction inputs changed during feedback execution")
    feedback["input_pins"] = after
    atomic_json(out / "construction-feedback.json", feedback)
    return feedback


def verify_delivery(task, base_dir, outdir):
    """Read-only rebind; this cannot submit or inherit any reviewer's judgment."""
    loaded = _load(task, base_dir)
    out = Path(outdir).resolve()
    admission = _read(out / "candidate-source-admission.json")
    if admission != _admission(loaded, task):
        raise ValueError("candidate admission/code/recipe/source changed; fresh admission required")
    feedback = _read(out / "construction-feedback.json")
    if (feedback["source_admission_id"] != admission["source_admission_id"]
            or feedback["input_pins"] != _input_pins(loaded["files"])
            or feedback["prior_reviews_carried"] or not feedback["requires_fresh_prospective_review"]):
        raise ValueError("candidate feedback source custody or review boundary differs")
    if (feedback["candidate_id"] != task["candidate"] or feedback["status"] != "passed"
            or feedback["construction_input_sha256"] != sources.digest(loaded["config_path"])
            or feedback["source_scope"] != loaded["config"]["source_scope"]
            or feedback["source_dependency_review"] != loaded["original"]["dependency_review"]
            or feedback["population_review"] != loaded["population_review"]
            or feedback["execution_authorized"] is not False or feedback["physics_validated"] is not False):
        raise ValueError("candidate feedback population/scope or authority boundary differs")
    if sources.digest(out / "candidate-task.json") != feedback["task_sha256"]:
        raise ValueError("retained candidate task differs")
    program, _ = construct(loaded["selected"]["recipe"], loaded["claims"])
    if _read(out / "constructed-program.json") != program:
        raise ValueError("delivered candidate program differs from source-bound construction")
    if feedback["candidate_disposition"] == "typed_compiler_refused":
        try:
            analysis_ir.compile_program(program, loaded["contract"])
        except ValueError as exc:
            if feedback["feedback"]["typed_compiler"] != {"status": "refused", "error": str(exc)}:
                raise ValueError("retained typed compiler feedback differs") from exc
        else:
            raise ValueError("asserted compiler refusal is absent from constructed program")
    if feedback["candidate_disposition"] in ("event_mismatch", "verified_on_supplied_events"):
        detached = _read(out / "standalone-verifier.json")
        report = analysis_witness.verify_bundle(out / "candidate-witness", detached["report"]["manifest_sha256"])
        if not report["passed"]:
            raise ValueError("retained candidate witness failed independent replay")
        actual = _reference_result(out / "candidate-witness")
        comparison = _compare_reference(loaded, actual)
        if comparison != feedback["feedback"]["upstream_comparison"]:
            raise ValueError("retained full upstream comparison differs")
        if (comparison["status"] == "passed") != (feedback["candidate_disposition"] == "verified_on_supplied_events"):
            raise ValueError("candidate disposition differs from complete event evidence")
    if loaded["selected"]["build"] is not None and feedback["feedback"].get("native_build", {}).get("status") == "passed":
        build_out = out / "native-build"
        plan, receipt = [_read(build_out / name) for name in ("build-plan.json", "build-receipt.json")]
        routine_build.verify_receipt(receipt, plan, plan["base_dir"], build_out)
    return {"status": "passed", "candidate_disposition": feedback["candidate_disposition"],
            "source_admission_id": admission["source_admission_id"], "physics_validated": False,
            "scope": "Read-only candidate source, complete event witness and retained build evidence rebind"}


def construction_output_schema(claim_ids):
    """AgentHost's closed public JSON interface; no executable text or commands."""
    ids = list(claim_ids)
    if not ids or len(ids) > 256 or len(set(ids)) != len(ids):
        raise ValueError("bounded unique source claims required")
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    def array(item, maximum, minimum=0):
        return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}
    def string(nullable=False, enum=None):
        value = {"type": ["string", "null"] if nullable else "string"}
        if enum is not None:
            value["enum"] = [*enum, None] if nullable else list(enum)
        return value
    names = string()
    number = {"type": ["number", "null"]}
    integer = {"type": ["integer", "null"], "minimum": 0, "maximum": 65536}
    flags = obj({"all": array(names, 64), "none": array(names, 64)})
    flags["type"] = ["object", "null"]
    arguments = array(names, 256); arguments["type"] = ["array", "null"]
    node = obj({"id": names, "op": string(enum=["input", "met", "const", "filter", "overlap", "overlap_vr",
        "concat", "sort", "take", "leading", "count", "sum_pt", "aplanarity", "ossf_pairs", "field", "mass",
        "mt", "mt_massless", "delta_phi", "min_dphi", "best_pair", "pair_mass", "add", "sub", "mul", "div",
        "min", "max", "compare", "sqrt", "abs", "and", "or", "not", "defined", "choose"]),
        "args": arguments, "collection": string(True, ("electron", "muon", "jet")),
        "value": number, "unit": string(True, analysis_ir.UNITS),
        "field": string(True, ("pt", "mass", "eta", "phi", "charge")),
        "comparison": string(True, analysis_ir.OPS), "count": integer, "index": integer,
        "flags": flags, "pt_from": string(True, ("candidate", "other"))})
    claims = array(string(enum=ids), 256, 1)
    return obj({"schema_version": {"type": "integer", "const": 1},
        "name": names, "steps": array(obj({"node": node, "claims": claims}), 256, 1),
        "regions": array(obj({"region": obj({"name": names, "cuts": array(names, 256, 1)}), "claims": claims}), 128, 1),
        "unserved_obligations": array(names, 64), "public_rationale": string()})


def prepare_agent_request(task, base_dir, graph_root, *, model, reasoning_effort,
                          max_output_tokens, requested_task, repair_ordinal=0, feedback=None):
    """Prepare/reserve the real AgentHost external invocation before dispatch.

    Evaluation events, expected source oracle, reference program, and existing
    hand-written candidate recipes are deliberately absent from initial model
    context. A later request sees retained actual feedback and its divergent
    events, while the graph retains its initial+two-repair call budget.
    Preparation does not execute a model or authorize a scientific worker.
    """
    from ravel.workflow import agent_graph
    loaded = _load(task, base_dir)
    if type(requested_task) is not str or not requested_task.strip() or len(requested_task) > 32000:
        raise ValueError("explicit bounded scientific construction request required")
    if type(repair_ordinal) is not int or not 0 <= repair_ordinal <= 2:
        raise ValueError("initial construction plus at most two repairs")
    if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000:
        raise ValueError("explicit bounded model output reservation required")
    root = Path(graph_root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("construction graph cannot traverse symlinks")
    exists = root.exists()
    if exists != (repair_ordinal > 0):
        raise ValueError("initial/new graph or revision/existing graph mismatch")
    capsule_path = _pin(loaded["config"]["source_capsule"], loaded["base"])
    capsule = sources.load_capsule(capsule_path)
    source_root, _ = sources.source_files(capsule, capsule_path.parent)
    # Entire analysis implementations and all explicitly claimed helper spans,
    # not an answer-key program or a producer's proposed interpretation.
    claimed_paths = {claim["path"] for claim in loaded["claims"].values()}
    source_text = []
    for fact in capsule["files"]:
        if fact["role"] != "compile" and fact["path"] not in claimed_paths:
            continue
        raw = (source_root / fact["path"]).read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError("claimed construction source exceeds model text bound")
        source_text.append({**fact, "text": raw.decode("utf-8")})
    panel = {"schema_version": 1, "kind": "agent-source-construction-request",
        "requested_task": requested_task, "repair_ordinal": repair_ordinal,
        "source_capsule_sha256": sources.digest(capsule_path), "source_inventory": loaded["original"],
        "source_scope": loaded["config"]["source_scope"], "source_claims": list(loaded["claims"].values()),
        "source_text": source_text, "object_contract": loaded["contract"],
        "event_domain": _read(_pin(loaded["config"]["event_domain"], loaded["base"])),
        "fixed_limits": deepcopy(loaded["selected"]["recipe"]["limits"]),
        "operator_contract": {"filter": "pT >= supplied threshold; abs(eta) < supplied bound. Flags are declared ID bit predicates.",
            "strict_lowering": "For finite binary64 supplied pT, use nextafter(x,+infinity) with >= for >x. The eta bound is already strict; retain its literal value. Preserve exact and neighboring boundary cases.",
            "field_eta": "Pseudorapidity only; rapidity equals it only in the explicitly massless jet domain.",
            "sort": "Descending pT with stable original-object ID tie break. Leading means index in the supplied collection.",
            "numeric_outputs": "Expose scalar and collection nodes in complete event traces; grouped histogram filling, finalization and normalization are separate unserved obligations unless explicitly implemented.",
            "vocabulary": "Only the output schema's closed analysis_ir operations; node arguments must reference earlier nodes."},
        "withheld": ["evaluation event population", "source oracle and expected decisions", "reference IR program", "existing finite candidate recipes"],
        "actual_feedback": None, "counterexample_events": [], "compute_authorized": False,
        "physics_validated": False}
    if repair_ordinal:
        if feedback is None:
            raise ValueError("repair model request requires retained actual feedback")
        feedback_path = _pin(feedback, loaded["base"])
        verify_delivery(task, base_dir, feedback_path.parent)
        full_feedback = _read(feedback_path)
        panel["actual_feedback"] = deepcopy(full_feedback)
        panel["actual_feedback"]["retained_full_feedback"] = deepcopy(feedback)
        differences = full_feedback.get("feedback", {}).get("upstream_comparison", {}).get("witnesses", [])
        selected_witnesses = _select_repair_witnesses(differences, loaded["events"])
        if "upstream_comparison" in panel["actual_feedback"].get("feedback", {}):
            panel["actual_feedback"]["feedback"]["upstream_comparison"]["witnesses"] = selected_witnesses
            panel["actual_feedback"]["feedback"]["upstream_comparison"]["witnesses_disclosed"] = len(selected_witnesses)
            panel["actual_feedback"]["feedback"]["upstream_comparison"]["witnesses_withheld"] = len(differences) - len(selected_witnesses)
        if panel["actual_feedback"]["candidate_disposition"] == "verified_on_supplied_events":
            raise ValueError("completed valid candidate does not admit a gratuitous repair")
        events_by_id = {event["event_id"]: event for event in loaded["events"]}
        panel["counterexample_events"] = [events_by_id[row["event_id"]] for row in selected_witnesses]
        panel["withheld"].remove("evaluation event population")
        panel["withheld"].append("evaluation events other than at most four retained counterexamples")
    schema = construction_output_schema(loaded["claims"])
    text = json.dumps(panel, sort_keys=True, allow_nan=False)
    if len(text.encode()) > 1_500_000:
        raise ValueError("construction source-only request exceeds explicit text bound")
    panel_path = loaded["base"] / ("agent-source-request-" + str(repair_ordinal) + ".json")
    if panel_path.exists():
        raise ValueError("model request already prepared; reuse exact reserved graph request")
    atomic_json(panel_path, panel)
    node = {"id": "construct", "kind": "model", "role": "proposer" if repair_ordinal == 0 else "improver",
        "depends_on": [], "inputs": [{"id": "construction-source", "path": str(panel_path), "sha256": sources.digest(panel_path)}],
        "packet": None, "action": "external", "max_attempts": 1,
        "parameters": {"instructions": "Construct the requested source-bound analysis_ir program from the supplied original source. Return only structured public JSON. All nullable node fields must be present; irrelevant ones must be null. Every node/region needs source claim IDs. Preserve complete applicable selection and ordering semantics and list unserved scientific obligations candidly. The request is advisory: no code execution, review authority or scientific approval. Do not infer withheld answers.",
            "model": model, "reasoning_effort": reasoning_effort, "max_output_tokens": max_output_tokens,
            "output_schema": schema}}
    specification = {"schema_version": 1, "graph_id": "source-routine-construction",
        "budget": {"max_nodes": 1, "max_calls": 3, "max_output_tokens": 3 * max_output_tokens,
                   "max_wall_seconds": 7200, "max_reworks": 2}, "nodes": [node]}
    if exists:
        state = agent_graph.status(root)
        if state["usage"]["calls"] != repair_ordinal:
            raise ValueError("repair ordinal differs from retained model call budget")
        agent_graph.revise(root, specification, reason="Fresh source-bound construction repair after actual retained feedback")
    else:
        agent_graph.create(root, specification)
    prepared = agent_graph.prepare_external(root, "construct")
    return {**prepared, "repair_ordinal": repair_ordinal, "source_panel": str(panel_path),
            "source_panel_sha256": sources.digest(panel_path), "model_executed": False,
            "compute_authorized": False, "expected_answers_withheld": True}


def materialize_agent_candidate(graph_root, *, source_task, base_dir, output_config, candidate_id):
    """Convert an actual receipted public model reply into a new immutable draft.

    This never overwrites an admitted board or carries review votes. The caller
    must obtain a fresh prospective science plan/approval before its worker.
    """
    from ravel.workflow import agent_graph
    loaded = _load(source_task, base_dir)
    graph_root = Path(graph_root).resolve()
    state = agent_graph.status(graph_root)
    reference = state["nodes"]["construct"].get("result")
    if state["nodes"]["construct"]["status"] != "completed" or not reference:
        raise ValueError("actual model construction response has not been delivered")
    receipt_path = graph_root / reference["path"]
    receipt = _read(receipt_path)
    if _digest(receipt) != reference["sha256"] or receipt["result_sha256"] != _digest(receipt["result"]):
        raise ValueError("actual model response receipt changed")
    raw = receipt["result"]["value"]
    from ravel.workflow.agent_host import validate_public_result
    validate_public_result(raw, construction_output_schema(loaded["claims"]))
    recipe = {"schema_version": 1, "name": raw["name"],
        "steps": [{"node": {key: value for key, value in step["node"].items() if value is not None},
                   "claims": step["claims"]} for step in raw["steps"]],
        "regions": raw["regions"], "limits": deepcopy(loaded["selected"]["recipe"]["limits"])}
    construct(recipe, loaded["claims"])
    config = deepcopy(loaded["config"])
    config["candidates"] = [{"id": _name(candidate_id), "parent": None, "recipe": recipe,
        "candidate_source_capsule": deepcopy(loaded["selected"]["candidate_source_capsule"]),
        "build": None, "reason": "Actual AgentHost model response; " + raw["public_rationale"]}]
    config["repair_board"] = []
    request_path = graph_root / state["nodes"]["construct"]["external_request"]["path"]
    panel_pin = receipt["request"]["input_artifacts"][0]
    config["model_construction"] = {"receipt":{"path":str(receipt_path),"sha256":sources.digest(receipt_path)},
        "request":{"path":str(request_path),"sha256":sources.digest(request_path)},
        "source_panel":{"path":panel_pin["path"],"sha256":panel_pin["sha256"]}}
    config["source_scope"]["unserved_obligations"] = list(dict.fromkeys(
        config["source_scope"]["unserved_obligations"] + raw["unserved_obligations"]))
    # All relative pins were declared against the input document's directory.
    # Keep the new document alongside it; moving requires explicit rebasing.
    output = Path(output_config).absolute()
    if output.parent.resolve() != loaded["base"] or output.exists():
        raise ValueError("new model draft must be a fresh same-directory construction configuration")
    atomic_json(output, config)
    binding = {"schema_version": 1, "kind": "actual-agent-routine-draft",
        "construction_input_sha256": sources.digest(output), "source_task_input_sha256": sources.digest(loaded["config_path"]),
        "model_receipt": {"path": str(receipt_path), "sha256": sources.digest(receipt_path)},
        "model_transport": receipt["result"]["transport"], "candidate_id": candidate_id,
        "prior_reviews_carried": [], "fresh_scientific_plan_required": True,
        "physics_validated": False, "compute_authorized": False}
    atomic_json(output.with_suffix(".model-receipt.json"), binding)
    return {"task": {"backend": "routine-candidate", "input": str(output), "candidate": candidate_id, "parent_feedback": None},
            "model_binding": binding}
