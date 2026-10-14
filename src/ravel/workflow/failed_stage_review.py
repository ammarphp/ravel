"""Read-only diagnostic intake for an actual failed scientific stage.

This adapter composes the existing execution observer, role-packet reader and
agent Graph. It does not create a physics-review cycle, vote, correction, runner,
or successful receipt. Capturing returned files NOW is not a successful stage's
execution-time output commitment. All successor experiments require a separately
approved prospective study with these exact failure and feedback pins.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from . import execution, physics_review, review_context
from .state_io import read_json

KINDS = {"infrastructure_failure", "scientific_unresolved"}
SHA = re.compile(r"^[0-9a-f]{64}$")
LIMITATION = ("Advisory failed-stage diagnosis only. The failed outcome and any partial results "
              "remain unaccepted. Capture-time custody is not an execution-time successful "
              "output receipt. Declared actor separation and observed transport do not prove "
              "scientific independence. No delivery, reuse, retry, correction or launch authority.")


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"{label} needs exactly {sorted(keys)}")


def _text(value, label):
    if type(value) is not str or not value.strip() or len(value) > 8192:
        raise ValueError(f"bounded explicit {label} required")


def _pin(value):
    _keys(value, {"path", "sha256"}, "artifact pin")
    _text(value["path"], "artifact path")
    if not SHA.fullmatch(str(value["sha256"])):
        raise ValueError("exact artifact SHA-256 required")


def validate(request):
    """Validate caller declarations without interpreting failure prose as fact."""
    _keys(request, {"schema_version", "stage_receipt", "failure_kind", "result",
                    "evidence", "required_returned_outputs"}, "failed-stage intake")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("failed-stage intake/v1 required")
    _pin(request["stage_receipt"])
    if request["failure_kind"] not in KINDS:
        raise ValueError("failed execution needs infrastructure_failure or scientific_unresolved; "
                         "a negative hypothesis from a successful experiment uses ordinary review")
    if request["result"] is not None:
        _pin(request["result"])
    elif request["failure_kind"] == "scientific_unresolved":
        raise ValueError("scientific unresolved intake needs an actual returned result")
    if type(request["evidence"]) is not list or not 1 <= len(request["evidence"]) <= 64:
        raise ValueError("bounded nonempty located evidence required")
    for ref in request["evidence"]:
        _keys(ref, {"path", "sha256", "location"}, "located evidence")
        _pin({k: ref[k] for k in ("path", "sha256")})
        _text(ref["location"], "evidence location")
    rows = request["required_returned_outputs"]
    if type(rows) is not list or len(rows) > 128 or len(set(rows)) != len(rows):
        raise ValueError("distinct bounded required returned outputs needed")
    for value in rows:
        _text(value, "required returned output")
        path = Path(value)
        if (path.is_absolute() or path.as_posix() != value
                or any(part in (".", "..") for part in path.parts)):
            raise ValueError("required returned outputs must be canonical run-relative paths")
    if request["failure_kind"] == "scientific_unresolved" and not rows:
        raise ValueError("scientific unresolved intake needs explicit returned-output obligations")
    return deepcopy(request)


def _bound(root, pin, session):
    path = session.regular_file(pin["path"], root)
    if session.hash_file(path) != pin["sha256"]:
        raise ValueError("failed-stage input changed: " + pin["path"])
    return path


def _files(snapshot):
    return [{"path": str(Path(path) if row["name"] == "." else Path(path) / row["name"]),
             "sha256": row["sha256"], "size": row["size"]}
            for path, entry in snapshot.items() for row in entry["files"]]


def _launch_binding(root, record, committed, session):
    """Bind the historical selected recipe without granting its old authority."""
    from . import launch_authorization
    reference = record.get("authorization_receipt")
    if reference is None:
        if record.get("child_pid") is not None or physics_review._science_run(root):
            raise ValueError("scientific failed-stage intake needs its retained observed launch")
        return {"execution_observation": "terminal_ledger_only", "pins": [],
                "limitations": ["No retained actual process launch; engineering ledger control only."]}
    _keys(reference, {"sequence", "sha256"}, "retained launch reference")
    directory = root / launch_authorization.JOURNAL
    session.require_inventory(directory)
    paths = sorted(directory.glob("*.json"))
    for path in paths:
        session.require_regular(path)
        session.read_document(path)
    events = launch_authorization._events(root)
    launched = next((e for e in events if e["sequence"] == reference["sequence"]), None)
    if (launched is None or launched["event"] != "launched" or launched["sha256"] != reference["sha256"]
            or launched.get("pid") != record.get("child_pid")):
        raise ValueError("failed stage does not bind the actual retained launch event")
    auth = next((e for e in events if e["sequence"] == launched.get("authorization_sequence")), None)
    if (auth is None or auth["event"] != "authorized" or auth["sha256"] != launched.get("authorization_sha256")
            or auth["sequence"] >= launched["sequence"] or auth.get("command") != record["command"]
            or auth.get("context", {}).get("stage") != record["stage"]):
        raise ValueError("failed launch differs from its retained historical recipe")
    # Compare every immutable optional metadata member with the selected binding,
    # rather than accepting a self-rehashed removed/changed helper declaration.
    selected = auth.get("authorization", {}).get("stage_binding")
    if physics_review._science_run(root) and selected is None:
        raise ValueError("failed scientific launch lacks its retained selected stage binding")
    if selected is not None and selected != {**committed, "fingerprint": record["fingerprint"]}:
        raise ValueError("failed stage changed the exact launched metadata or specification")
    return {"execution_observation": "retained_launch_bound", "launch_sha256": launched["sha256"],
            "authorization_sha256": auth["sha256"],
            "pins": [{"path": str(p), "sha256": session.hash_file(p)} for p in paths],
            "limitations": ["Retained launch custody only; original approval is not reissued or inherited."]}


def _observe(request, root, session):
    record_path = _bound(root, request["stage_receipt"], session)
    record = session.read_document(record_path)
    stage = record.get("stage") if type(record) is dict else None
    if (type(stage) is not str or not execution.NAME.fullmatch(stage)
            or not record.get("attempt_id") or record.get("status") != "failed"
            or type(record.get("exit_code")) is not int or record["exit_code"] == 0
            or not record.get("finished_utc")):
        raise ValueError("diagnostic intake requires a terminal actual FAILED attempt with nonzero exit")
    state = session.read_document(root / execution.STATE_NAME)
    ledger_pin = {"path": str(root / execution.STATE_NAME),
                  "sha256": session.hash_file(root / execution.STATE_NAME)}
    if (state["stages"].get(stage) != record
            or session.regular_file(record["attempt_record"], root) != record_path):
        raise ValueError("failed stage must be the exact current retained execution attempt")
    committed = {k: record[k] for k in
                 ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")}
    # These are the exact immutable metadata members of the recorded stage
    # fingerprint, NOT current-runtime helper/resource admission. Calling the
    # latter here would require the historical helper's source path to equal the
    # diagnostic adapter's new package path. We never execute/import that source.
    metadata = {k: deepcopy(record[k]) for k in
                ("output_policy", "helper_declaration", "operation_resources") if k in record}
    committed.update(metadata)
    if execution.digest(committed) != record.get("fingerprint"):
        raise ValueError("failed stage specification fingerprint changed")
    launch = _launch_binding(root, record, committed, session)
    # Retain the original recorded runtime. The current observer is separately
    # checked by finish(); it cannot turn a historical failure into a reuse pass.
    if session.snapshot(record["inputs"]) != record["input_snapshot"]:
        raise ValueError("failed stage sources or inputs changed")
    for file in _files(record["input_snapshot"]):
        session.require_regular(file["path"])
    for parent, sha in record["parents"].items():
        errors = execution.stage_errors(root, parent, state, _session=session)
        if errors or state["stages"].get(parent, {}).get("receipt_sha256") != sha:
            raise ValueError("failed stage parent evidence changed: " + parent)
    returned, missing = {}, []
    for value in record["outputs"]:
        path = execution.resolve_path(root, value, output=True)
        session.require_inventory(path)
        if not path.exists():
            missing.append(str(path))
            continue
        # outputs=False deliberately retains empty/malformed failure witnesses.
        # They are classified explicitly below, never admitted as scientific data.
        try:
            returned.update(session.snapshot([str(path)]))
        except ValueError as exc:
            if not path.is_dir() or any(path.iterdir()):
                raise
            missing.append(str(path))
    returned_files = _files(returned)
    for file in returned_files:
        session.require_regular(file["path"])
    actual_outputs = {row["path"]: row for row in returned_files}
    obligations = []
    for value in request["required_returned_outputs"]:
        path = str(execution.resolve_path(root, value, output=True))
        if not any(Path(path) == execution.resolve_path(root, out, output=True)
                   or Path(path).is_relative_to(execution.resolve_path(root, out, output=True))
                   for out in record["outputs"]):
            raise ValueError("required output is outside the actual stage output declaration")
        found = actual_outputs.get(path)
        obligations.append({"path": path, "status": "missing" if found is None else
                            "empty" if found["size"] == 0 else "returned"})
    if request["failure_kind"] == "scientific_unresolved" and (
            missing or any(row["status"] != "returned" for row in obligations)):
        raise ValueError("missing/empty returned scientific evidence is infrastructure failure, not unresolved science")
    if request["failure_kind"] == "scientific_unresolved":
        for row in obligations:
            if Path(row["path"]).suffix.lower() == ".json":
                try:
                    session.read_document(Path(row["path"]))
                except (ValueError, UnicodeError) as exc:
                    raise ValueError("malformed required numerical output is infrastructure failure, "
                                     "not unresolved science: " + row["path"]) from exc
    result = None
    if request["result"] is not None:
        result_path = _bound(root, request["result"], session)
        if str(result_path) not in actual_outputs or actual_outputs[str(result_path)]["size"] == 0:
            raise ValueError("actual result must be a nonempty returned output of this failed attempt")
        result = session.read_document(result_path)
        if type(result) is not dict:
            raise ValueError("actual scientific result must be an object")
        if (result.get("status") in {"pass", "passed", "success", "succeeded", "accepted"}
                or result.get("physics_validated") is True):
            raise ValueError("a FAILED diagnostic intake cannot promote a successful or validated result claim")
        if request["failure_kind"] == "scientific_unresolved" and (
                result.get("status") not in {"failed", "unresolved", "inconclusive"}
                or result.get("fatal") is not None or result.get("custody_refusal") is not None):
            raise ValueError("scientific unresolved evidence must retain an unresolved outcome without infrastructure fatal/refusal")
    evidence = []
    for ref in request["evidence"]:
        path = _bound(root, ref, session)
        if path.stat().st_size == 0:
            raise ValueError("located diagnostic evidence must be nonempty")
        evidence.append({"path": str(path), "sha256": ref["sha256"],
                         "size": path.stat().st_size, "location": ref["location"]})
    policy_path = root / physics_review.POLICY
    actors = None
    if policy_path.exists():
        policy = session.read_document(policy_path)
        errors = physics_review.validate_policy(policy)
        if errors:
            raise ValueError("invalid original review policy: " + "; ".join(errors))
        # A review policy supplies only declared roles; diagnostic intake grants
        # none of its claim actions, correction bounds or approval authority.
        if str(policy_path) not in record["input_snapshot"]:
            raise ValueError("diagnostic actors need the exact policy bound as an actual stage input")
        actors = policy["actors"]
    result_pin = None if request["result"] is None else {
        "path": str(_bound(root, request["result"], session)), "sha256": request["result"]["sha256"]}
    document = {"schema_version": 1, "kind": "failed_stage_diagnostic_intake",
        "run_dir": str(root), "stage": stage, "attempt_id": record["attempt_id"],
        "record": {"path": str(record_path), "sha256": request["stage_receipt"]["sha256"]},
        "execution_ledger": ledger_pin,
        "fingerprint": record["fingerprint"], "recorded_stage_metadata": metadata,
        "failure_kind": request["failure_kind"],
        "stage_status": record["status"], "exit_code": record["exit_code"],
        "execution_error": record.get("error"), "recorded_runtime": record["runtime"],
        "launch_observation": launch,
        "source_inputs": deepcopy(record["input_snapshot"]), "parent_receipts": deepcopy(record["parents"]),
        "returned_outputs": returned, "missing_output_roots": missing,
        "returned_output_obligations": obligations, "result": result_pin,
        "result_status": None if result is None else result.get("status"),
        "evidence": evidence, "actors": actors, "request": request,
        "output_custody": "fresh capture of retained bytes; no successful execution output commitment",
        "execution_authorized": False, "scientific_acceptance": False, "delivery_authorized": False,
        "reuse_authorized": False, "correction_authorized": False, "automatic_redo": False,
        "prior_reviews_carried": [], "limitations": [LIMITATION]}
    document["sha256"] = execution.digest(document)
    return document


def intake(request, *, base_dir):
    """Observe a genuine current failure. This function writes nothing to its run."""
    request = validate(request)
    root = physics_review._root(base_dir)
    session = execution._validation_session(root)
    try:
        session.track(request)
        document = _observe(request, root, session)
        session.track(document)
        errors = session.finish()
        if errors:
            raise ValueError("; ".join(errors))
        return document
    finally:
        session.close()


def verify(document, *, base_dir):
    """Re-observe complete live custody; stale premises cannot guide new work."""
    if (type(document) is not dict or document.get("kind") != "failed_stage_diagnostic_intake"
            or document.get("sha256") != execution.digest({k: v for k, v in document.items() if k != "sha256"})
            or document.get("run_dir") != str(Path(base_dir).resolve())):
        raise ValueError("failed diagnostic document identity changed")
    if intake(document["request"], base_dir=base_dir) != document:
        raise ValueError("failed diagnostic premise is stale")
    return deepcopy(document)


def inputs(request, *, base_dir):
    """Complete file dependency list, including returned census and failure log."""
    document = intake(request, base_dir=base_dir)
    pins = [document["record"], document["execution_ledger"], *document["launch_observation"]["pins"]]
    pins.extend({k: row[k] for k in ("path", "sha256")} for row in
                [*_files(document["source_inputs"]), *_files(document["returned_outputs"]), *document["evidence"]])
    unique = {}
    for pin in pins:
        if pin["path"] in unique and unique[pin["path"]] != pin:
            raise ValueError("conflicting failed-stage dependencies")
        unique[pin["path"]] = pin
    return list(unique.values())


def _write_new(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _census_summary(snapshot):
    files = sorted(_files(snapshot), key=lambda row: row["path"])
    suffixes = {}
    for row in files:
        suffix = Path(row["path"]).suffix
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
    return {"root_count": len(snapshot), "file_count": len(files),
        "bytes": sum(row["size"] for row in files), "sha256": execution.digest(snapshot),
        "suffix_counts": dict(sorted(suffixes.items())[:32]),
        "other_suffix_files": sum(v for _, v in sorted(suffixes.items())[32:]),
        "path_samples": files[:2] + (files[-2:] if len(files) > 2 else []),
        "complete_index": "full_premise; input/returned ordinal indexes sort full file paths"}


def _bounded_premise(document):
    """Material failure/unknowns and exact complete census commitments, not a new intake."""
    value = deepcopy(document)
    value["kind"] = "failed_stage_diagnostic_presentation"
    value["presentation_of"] = document["sha256"]
    value["source_inputs"] = _census_summary(document["source_inputs"])
    value["returned_outputs"] = _census_summary(document["returned_outputs"])
    root = Path(document["run_dir"])
    material = [row for row in sorted(_files(document["source_inputs"]), key=lambda r: r["path"])
                if Path(row["path"]).parent == root / "inputs"]
    value["material_input_pins"] = material[:32]
    value["material_input_count"] = len(material)
    value["numerical_outcome"] = ("no returned numerical result; no numerical conclusion"
        if document["result"] is None else "partial/unresolved result; no repaired or accepted conclusion")
    value["scientific_contract"] = None
    for row in material:
        if Path(row["path"]).name == "science.json":
            if row["size"] <= 65536:
                with Path(row["path"]).open("rb") as stream:
                    raw = stream.read(row["size"] + 1)
                if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise ValueError("diagnostic scientific contract changed")
                spec = review_context._strict_json_bytes(raw)
                value["scientific_contract"] = {"source": row,
                    "content": {key: spec[key] for key in ("schema_version", "mode", "task", "source", "assumptions", "max_seconds", "max_attempts") if key in spec}}
            else:
                value["scientific_contract"] = {"source": row, "content": None,
                    "limitation": "select bounded input pages; scientific contract exceeds initial presentation bound"}
    value["on_demand"] = {"full_intake_artifact": "full_premise", "page_bytes_max": 65536,
        "ordinary_read": "review-context read --offset N --max-bytes B; review-read Graph tool",
        "fresh_role": "prepare-failed-role --evidence-pages JSON; API evidence_pages",
        "selection": "full_premise, eNNNN, inputNNNNNN or returnedNNNNNN; source ordinals sort full file paths",
        "limitation": "initial model invocation has no tools; coordinator selects pages into a fresh role context; no automatic read or retry"}
    return value


def _project_diagnostic_bytes(raw, role, path):
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError):
        value = None
    projection = "exact located diagnostic evidence"
    if role in {"critic", "verifier"} and value is not None:
        projected = review_context._project_known_judgments(value)
        if projected is None:
            projected = review_context._project_science_artifact(value, str(path))
        if projected is not None:
            value, projection = projected
            raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    return raw, projection


def _selected_content(document, identity, role, root):
    source = re.fullmatch(r"(input|returned)([0-9]{6})", identity)
    if source is None:
        raise ValueError("diagnostic page is outside complete source/returned allowlist")
    census = document["source_inputs" if source[1] == "input" else "returned_outputs"]
    rows = sorted(_files(census), key=lambda row: row["path"])
    ordinal = int(source[2])
    if ordinal >= len(rows):
        raise ValueError("diagnostic source page ordinal is absent")
    ref = rows[ordinal]; path = physics_review._path(root, ref["path"])
    if ref["size"] > 16 * 1024**2:
        raise ValueError("source exceeds retained artifact bound; use a separately bounded witness")
    with path.open("rb") as stream:
        raw = stream.read(ref["size"] + 1)
    if len(raw) != ref["size"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("diagnostic selected source changed")
    raw, projection = _project_diagnostic_bytes(raw, role, path)
    return raw, ref, projection


def create_context(document, role, out, *, base_dir, max_file_bytes=2_000_000, evidence_pages=None):
    """Existing Graph/Host-compatible role packet; no ordinary review registration."""
    document = verify(document, base_dir=base_dir)
    if role not in review_context.ROLES or type(max_file_bytes) is not int or max_file_bytes <= 0:
        raise ValueError("known diagnostic role and positive context bound required")
    out = review_context._safe_path(out)
    if out.exists():
        raise FileExistsError("diagnostic context already exists")
    root = Path(base_dir).resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError("diagnostic contexts must be separate from immutable failed run history")
    # The exact premise is presented to every role. It includes custody and
    # failure class, but no numerical acceptance or favorable proposal judgment.
    full_raw = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
    bounded = len(full_raw) > max_file_bytes or bool(evidence_pages)
    contents = [("premise", _bounded_premise(document) if bounded else document, document["sha256"],
        "bounded material failure and complete census commitments" if bounded else "diagnostic premise and complete returned/missing/source census")]
    deferred = set()
    source_paths = {"premise": str(root), "full_premise": str(root)}
    if bounded:
        if len(full_raw) > 16 * 1024**2:
            raise ValueError("complete diagnostic intake exceeds retained artifact bound")
        contents.append(("full_premise", full_raw, document["sha256"], "complete immutable failed intake; on-demand presentation"))
        deferred.add("full_premise")
    omissions = []
    for index, ref in enumerate(document["evidence"]):
        path = physics_review._path(root, ref["path"])
        if path.stat().st_size > max_file_bytes and (not bounded or path.stat().st_size > 16 * 1024**2):
            omissions.append({"source_path": str(path), "source_sha256": ref["sha256"],
                              "reason": "request a bounded witness for oversized evidence", "location": ref["location"]})
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("diagnostic role evidence changed")
        raw, projection = _project_diagnostic_bytes(raw, role, path)
        identity = f"e{index:04d}"
        contents.append((identity, raw, ref["sha256"], projection))
        source_paths[identity] = str(path)
        if len(raw) > max_file_bytes: deferred.add(identity)
    if evidence_pages is not None:
        if type(evidence_pages) is not list or len(evidence_pages) > 32:
            raise ValueError("at most 32 explicit diagnostic pages required")
        seen = set()
        for index, page in enumerate(evidence_pages):
            _keys(page, {"artifact_id", "offset", "max_bytes"}, "diagnostic evidence page")
            identity = page["artifact_id"]
            if type(identity) is not str:
                raise ValueError("diagnostic page identity required")
            match = next((row for row in contents if row[0] == identity), None)
            if match is None:
                raw, ref, projection = _selected_content(document, identity, role, root)
                match = (identity, raw, ref["sha256"], projection)
                contents.append(match); deferred.add(identity)
                source_paths[identity] = ref["path"]
            raw = match[1] if type(match[1]) is bytes else (json.dumps(match[1], indent=2, allow_nan=False) + "\n").encode()
            payload = review_context._artifact_page(raw, identity, offset=page["offset"], max_bytes=page["max_bytes"])
            key = (identity, page["offset"], page["max_bytes"])
            if key in seen: raise ValueError("duplicate diagnostic evidence page")
            seen.add(key)
            contents.append((f"p{index:04d}", payload, match[2], "exact selected authenticated byte page; no semantic inference"))
            source_paths[f"p{index:04d}"] = source_paths[identity]
    manifest = {"schema_version": 1, "role": role, "run_id": str(root),
        "cycle_id": document["sha256"], "source_event_sha256": document["sha256"],
        "artifacts": [], "omissions": omissions, "findings": [], "reviews": [],
        "allowed_claim_scopes": {}, "required_checks": [], "access_limitation": LIMITATION}
    projected_files = []
    for identity, value, source_sha, projection in contents:
        raw = value if type(value) is bytes else (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
        if identity not in deferred and len(raw) > max_file_bytes:
            raise ValueError("diagnostic premise exceeds context bound; use an explicit bounded intake")
        relative = f"artifacts/{identity}.json" if identity == "premise" else f"artifacts/{identity}.txt"
        projected_files.append((relative, raw))
        manifest["artifacts"].append({"id": identity, "path": relative,
            "source_path": source_paths[identity],
            "source_sha256": source_sha, "sha256": hashlib.sha256(raw).hexdigest(), "projection": projection})
        if identity in deferred:
            manifest["artifacts"][-1]["presentation"] = "on_demand"
    manifest["sha256"] = execution.digest(manifest)
    # Re-observe AFTER copying bytes and BEFORE publishing a usable role packet.
    verify(document, base_dir=base_dir)
    out.mkdir(parents=True, exist_ok=False)
    (out / "artifacts").mkdir()
    for relative, raw in projected_files:
        with (out / relative).open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    _write_new(out / "manifest.json", manifest)
    return manifest


def graph_feedback(document, critic_binding, verifier_binding, *, base_dir, allow_control=False):
    """Retain actual separate Graph critiques, never cast ordinary acceptance votes.

    The improver proposal remains the caller's existing Graph-bound revision
    operation. A verifier here assesses failure diagnosis and experiment design;
    it cannot certify repaired numerical results that have not been executed.
    """
    from . import agent_graph
    document = verify(document, base_dir=base_dir)
    if type(allow_control) is not bool:
        raise ValueError("explicit control policy required")
    if document["actors"] is None:
        raise ValueError("actual diagnostic roles need an original source-bound role policy")
    if document["launch_observation"]["execution_observation"] != "retained_launch_bound" and not allow_control:
        raise ValueError("genuine scientific feedback needs a retained actual launch; ledger-only controls remain controls")
    receipts = []
    for role, key, binding in (("critic", "physics_critic", critic_binding),
                               ("verifier", "skeptical_verifier", verifier_binding)):
        _keys(binding, {"graph_root", "node_id", "context_manifest_sha256", "actor_id"}, "diagnostic Graph binding")
        if binding["actor_id"] != document["actors"][key]:
            raise ValueError("diagnostic actor differs from source-bound original policy")
        receipt = agent_graph.model_receipt(binding["graph_root"], binding["node_id"],
            expected_subject_sha256=document["sha256"],
            expected_packet_sha256=binding["context_manifest_sha256"], require_exact_subject=False)
        # Exact intake bytes have their normal JSON serialization hash, while
        # its canonical document SHA is the source identity in the packet.
        spec, _ = agent_graph._load(Path(binding["graph_root"]))
        node = next(n for n in spec["nodes"] if n["id"] == binding["node_id"])
        manifest = read_json(Path(node["packet"]["path"]) / "manifest.json")
        if (receipt["role"] != role or manifest.get("source_event_sha256") != document["sha256"]
                or manifest.get("role") != role or manifest.get("allowed_claim_scopes") != {}
                or not any(a["id"] == "premise" and a["source_sha256"] == document["sha256"]
                           for a in manifest["artifacts"])):
            raise ValueError("diagnostic review does not bind the exact failed subject and matching role packet")
        raw = review_context.read_artifact(node["packet"]["path"], "premise",
            expected_manifest_sha256=binding["context_manifest_sha256"])
        premise_entry = next(a for a in manifest["artifacts"] if a["id"] == "premise")
        if premise_entry.get("presentation", "inline") != "inline":
            raise ValueError("diagnostic material summary must be presented inline")
        presented = json.loads(raw)
        bounded_presentation = presented != document
        if presented != document:
            full_entry = next((a for a in manifest["artifacts"] if a["id"] == "full_premise"), None)
            if full_entry is None or full_entry.get("presentation") != "on_demand" or full_entry["source_sha256"] != document["sha256"]:
                raise ValueError("complete diagnostic premise must retain its exact on-demand binding")
            if presented != _bounded_premise(document):
                raise ValueError("diagnostic bounded presentation differs from exact failed premise")
            full = review_context.read_artifact(node["packet"]["path"], "full_premise",
                expected_manifest_sha256=binding["context_manifest_sha256"])
            if json.loads(full) != document:
                raise ValueError("diagnostic complete retained premise changed")
        for entry in manifest["artifacts"]:
            source = re.fullmatch(r"(input|returned)([0-9]{6})", entry["id"])
            if source:
                selected, ref, _ = _selected_content(document, entry["id"], role, Path(base_dir).resolve())
                if (entry["sha256"] != hashlib.sha256(selected).hexdigest() or entry["source_sha256"] != ref["sha256"]
                        or entry["source_path"] != ref["path"]):
                    raise ValueError("diagnostic selected file differs from complete canonical census")
            if re.fullmatch(r"p[0-9]{4}", entry["id"]):
                if entry.get("presentation", "inline") != "inline":
                    raise ValueError("selected diagnostic page must be presented inline")
                page = json.loads(review_context.read_artifact(node["packet"]["path"], entry["id"],
                    expected_manifest_sha256=binding["context_manifest_sha256"]))
                identity = page.get("artifact_id")
                if type(identity) is not str or not re.fullmatch(r"full_premise|e[0-9]{4}|(?:input|returned)[0-9]{6}", identity):
                    raise ValueError("diagnostic selected page parent is invalid")
                parent = review_context.read_artifact(node["packet"]["path"], identity,
                    expected_manifest_sha256=binding["context_manifest_sha256"])
                length = page.get("bytes")
                if type(length) is not int or not 0 <= length <= 65536 or page != review_context._artifact_page(parent, identity,
                        offset=page.get("offset"), max_bytes=max(1, length)):
                    raise ValueError("diagnostic selected page differs from its authenticated full artifact")
        live = receipt["execution_observation"] in {"host_attested_external", "remote_transport_observed", "local_transport_observed"}
        control = allow_control and receipt["execution_observation"] == "control_only"
        if not (live or control) or not receipt["context_transport_separated"]:
            raise ValueError("diagnostic review needs an observed fresh separated transport; manual attestations cannot count")
        row = {"actor_id": binding["actor_id"], "binding": deepcopy(binding), "receipt": receipt}
        if bounded_presentation:
            row["presentation"] = {"initial": "bounded material summary", "complete_intake": "authenticated on_demand",
                "all_source_contents_presented": False, "automatic_page_read": False}
        receipts.append(row)
    if (receipts[0]["receipt"]["request_id"] == receipts[1]["receipt"]["request_id"]
            or receipts[0]["receipt"]["context_manifest_sha256"] == receipts[1]["receipt"]["context_manifest_sha256"]):
        raise ValueError("critic and verifier require separate actual requests and role packets")
    verify(document, base_dir=base_dir)
    for row in receipts:
        binding = row["binding"]
        fresh = agent_graph.model_receipt(binding["graph_root"], binding["node_id"],
            expected_subject_sha256=document["sha256"],
            expected_packet_sha256=binding["context_manifest_sha256"], require_exact_subject=False)
        if fresh != row["receipt"]:
            raise ValueError("diagnostic Graph review changed before feedback return")
    feedback = {"schema_version": 1, "kind": "failed_stage_diagnostic_feedback",
        "parent_failure_sha256": document["sha256"], "run_dir": document["run_dir"],
        "stage": document["stage"], "attempt_id": document["attempt_id"],
        "failure_kind": document["failure_kind"], "stage_status": "failed", "reviews": receipts,
        "scientific_acceptance": False, "execution_authorized": False, "delivery_authorized": False,
        "reuse_authorized": False, "automatic_redo": False, "prior_reviews_carried": [],
        "control_only": (document["launch_observation"]["execution_observation"] != "retained_launch_bound"
                         or any(r["receipt"]["execution_observation"] == "control_only" for r in receipts)),
        "next_action": "new_prospective_experiment_design", "limitations": [LIMITATION]}
    feedback["sha256"] = execution.digest(feedback)
    return feedback


def historical_feedback(document, index_pin, critic_binding, verifier_binding, *, base_dir):
    """Bind existing attributed reports without inventing past Graph transport.

    Located actor/subject fields and file custody are checked. This does not
    authenticate report authorship, establish fresh context, or convert a source
    review into a live model-call receipt or numerical acceptance vote.
    """
    from .diagnostic_plan import pointer
    document = verify(document, base_dir=base_dir)
    if document["actors"] is None:
        raise ValueError("historical report attribution needs the original bound role policy")
    _pin(index_pin)
    root = Path(base_dir).resolve()
    session = execution._validation_session(root)
    try:
        index_path = _bound(root, index_pin, session)
        index = session.read_document(index_path)
        if type(index) is not dict or type(index.get("pins")) is not list or not 1 <= len(index["pins"]) <= 512:
            raise ValueError("explicit bounded historical diagnostic index required")
        indexed = {}
        for pin in index["pins"]:
            _pin(pin)
            path = _bound(root, pin, session)
            indexed[str(path)] = pin["sha256"]
        known = {row["path"]: row["sha256"] for row in
                 [document["record"], *_files(document["source_inputs"]),
                  *_files(document["returned_outputs"]), *document["evidence"]]}
        reviews = []
        for role, policy_role, binding in (("critic", "physics_critic", critic_binding),
                                          ("verifier", "skeptical_verifier", verifier_binding)):
            _keys(binding, {"actor_id", "report", "actor_pointer", "subject", "subject_pointer"},
                  "historical diagnostic binding")
            _pin(binding["report"]); _pin(binding["subject"])
            for key in ("actor_pointer", "subject_pointer"):
                _text(binding[key], "located report pointer")
            if binding["actor_id"] != document["actors"][policy_role]:
                raise ValueError("historical diagnostic actor differs from original declared role")
            report_path = _bound(root, binding["report"], session)
            subject_path = _bound(root, binding["subject"], session)
            if (indexed.get(str(report_path)) != binding["report"]["sha256"]
                    or indexed.get(str(subject_path)) != binding["subject"]["sha256"]
                    or known.get(str(subject_path)) != binding["subject"]["sha256"]):
                raise ValueError("historical index/report must bind the exact failed-stage evidence")
            report = session.read_document(report_path)
            try:
                actor = pointer(report, binding["actor_pointer"])
                subject = pointer(report, binding["subject_pointer"])
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError("historical report actor or subject location is absent") from exc
            subject_matches = subject == binding["subject"]["sha256"]
            if type(subject) is dict and {"path", "sha256"} <= set(subject):
                subject_matches = (session.regular_file(subject["path"], report_path.parent) == subject_path
                                   and subject["sha256"] == binding["subject"]["sha256"])
            if actor != binding["actor_id"] or not subject_matches:
                raise ValueError("historical report does not locate its declared actor and failed subject")
            reviews.append({"role": role, "actor_id": binding["actor_id"],
                "report": {"path": str(report_path), "sha256": binding["report"]["sha256"]},
                "subject": {"path": str(subject_path), "sha256": binding["subject"]["sha256"]},
                "actor_pointer": binding["actor_pointer"], "subject_pointer": binding["subject_pointer"],
                "authorship_authenticated": False, "graph_model_receipt": None,
                "fresh_context_observed": False})
        if (reviews[0]["report"]["path"] == reviews[1]["report"]["path"]
                or reviews[0]["report"]["sha256"] == reviews[1]["report"]["sha256"]
                or reviews[0]["subject"] != reviews[1]["subject"]):
            raise ValueError("historical critic/verifier need distinct reports on the same exact failed subject")
        result = {"schema_version": 1, "kind": "failed_stage_historical_feedback",
            "parent_failure_sha256": document["sha256"], "run_dir": document["run_dir"],
            "stage": document["stage"], "attempt_id": document["attempt_id"],
            "failure_kind": document["failure_kind"], "stage_status": "failed",
            "index": {"path": str(index_path), "sha256": index_pin["sha256"]},
            "bindings": {"critic": deepcopy(critic_binding), "verifier": deepcopy(verifier_binding)},
            "reviews": reviews, "feedback_source": "retained_attributed_reports",
            "fresh_role_transport_observed": False, "new_model_calls": 0,
            "scientific_acceptance": False, "execution_authorized": False,
            "delivery_authorized": False, "reuse_authorized": False, "automatic_redo": False,
            "prior_reviews_carried": [], "next_action": "new_prospective_experiment_design",
            "control_only": document["launch_observation"]["execution_observation"] != "retained_launch_bound",
            "limitations": [LIMITATION, "Historical attributed reports have file/located-field custody, "
                "not observed AgentGraph generation, fresh blinding or authenticated authorship."]}
        result["sha256"] = execution.digest(result)
        session.track(result)
        verify(document, base_dir=base_dir)
        errors = session.finish()
        if errors:
            raise ValueError("; ".join(errors))
        return result
    finally:
        session.close()


def verify_feedback(document, feedback, *, base_dir, allow_control=False):
    """Revalidate exact prior diagnostic evidence without importing its verdict."""
    if (type(feedback) is not dict or feedback.get("sha256") != execution.digest(
            {k: v for k, v in feedback.items() if k != "sha256"})):
        raise ValueError("diagnostic feedback identity changed")
    if feedback.get("kind") == "failed_stage_historical_feedback":
        result = historical_feedback(document, feedback["index"], feedback["bindings"]["critic"],
                                     feedback["bindings"]["verifier"], base_dir=base_dir)
    elif feedback.get("kind") == "failed_stage_diagnostic_feedback":
        result = graph_feedback(document, *[r["binding"] for r in feedback["reviews"]],
                                base_dir=base_dir, allow_control=allow_control)
    else:
        raise ValueError("known diagnostic feedback kind required")
    if result != feedback or (feedback["control_only"] and not allow_control):
        raise ValueError("diagnostic feedback is stale or remains an engineering control")
    return deepcopy(feedback)


def bind_successor(document, feedback, proposal_pin, candidate_inputs, *, base_dir):
    """Bind a prospective source intervention to the actual failure and critique.

    This is an input to the existing research-cycle design operation, not a new
    experiment planner or execution contract. The caller still supplies its full
    hypotheses, rival predictions, held-fixed quantities, rechecks and resources
    to that operation and to the ordinary scientific-study intake.
    """
    document = verify(document, base_dir=base_dir)
    feedback = verify_feedback(document, feedback, base_dir=base_dir)
    _pin(proposal_pin)
    if type(candidate_inputs) is not list or not 1 <= len(candidate_inputs) <= 64:
        raise ValueError("complete bounded prospective candidate source inputs required")
    root = Path(base_dir).resolve()
    session = execution._validation_session(root)
    try:
        proposal_path = _bound(root, proposal_pin, session)
        if proposal_path.stat().st_size == 0:
            raise ValueError("prospective intervention proposal must be nonempty")
        pins = []
        for pin in candidate_inputs:
            _pin(pin)
            path = _bound(root, pin, session)
            if path.stat().st_size == 0:
                raise ValueError("prospective scientific/source input must be nonempty")
            pins.append({"path": str(path), "sha256": pin["sha256"]})
        if len({p["path"] for p in pins}) != len(pins):
            raise ValueError("distinct prospective candidate input identities required")
        result = {"schema_version": 1, "kind": "failed_stage_prospective_source_binding",
            "parent_failure_sha256": document["sha256"], "diagnostic_feedback_sha256": feedback["sha256"],
            "feedback_source": feedback.get("feedback_source", "current_graph_model_receipts"),
            "fresh_role_transport_observed": feedback.get("fresh_role_transport_observed", True),
            "failed_record": document["record"], "failed_attempt_id": document["attempt_id"],
            "failure_kind": document["failure_kind"], "parent_stage_status": "failed",
            "parent_source_inputs_sha256": execution.digest(document["source_inputs"]),
            "parent_returned_outputs_sha256": execution.digest(document["returned_outputs"]),
            "parent_result": document["result"],
            "proposal": {"path": str(proposal_path), "sha256": proposal_pin["sha256"]},
            "candidate_inputs": pins, "new_scientific_plan_required": True,
            "new_execution_approval_required": True, "new_result_review_required": True,
            "prior_reviews_carried": [], "scientific_acceptance": False,
            "execution_authorized": False, "delivery_authorized": False, "reuse_authorized": False,
            "automatic_redo": False, "limitations": [LIMITATION,
                "Source binding does not judge intervention correctness, discharge prospective resource "
                "admission, or close numerical objections before new execution."]}
        result["sha256"] = execution.digest(result)
        session.track(result)
        verify_feedback(document, feedback, base_dir=base_dir)
        errors = session.finish()
        if errors:
            raise ValueError("; ".join(errors))
        return result
    finally:
        session.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rundir", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    document = intake(read_json(args.request), base_dir=args.rundir)
    out = review_context._safe_path(args.out)
    root = Path(args.rundir).resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError("diagnostic intake output must preserve the original failed run")
    _write_new(out, document)
    print(json.dumps({"path": str(out), "sha256": document["sha256"],
                      "stage_status": "failed", "scientific_acceptance": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
