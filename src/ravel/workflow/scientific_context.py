"""Task-directed source/API context and scientific step carryover.

No supplied source is imported, no tool is installed or executed, and no model is
called. Output checks establish completion of explicitly requested quantities in
supplied artifacts, not runtime consumption, statistical qualification or physics.
The ordinary AgentGraph remains the scheduler, budget and request lifecycle.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from ravel import analysis_sources
from ravel.workflow import state_io
from ravel.workflow.state_io import atomic_json, file_lock, read_json

MAX_SOURCE = 16_000_000
MAX_CONTEXT = 512_000
MAX_STEPS = 32


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("invalid " + label + " fields")


def _text(value, label, maximum=16000):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded nonempty " + label + " required")


def _integer(value, label, minimum=1, maximum=MAX_SOURCE):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("bounded integer " + label + " required")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _path(value, base):
    raw = Path(value)
    path = raw if raw.is_absolute() else Path(base) / raw
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("ordinary existing input required: " + str(path))
    return path.absolute()


def _read(pin, base, maximum=MAX_SOURCE):
    _keys(pin, ("path", "sha256"), "input pin")
    if not re.fullmatch(r"[0-9a-f]{64}", str(pin["sha256"])):
        raise ValueError("exact SHA256 required")
    path = _path(pin["path"], base)
    if path.stat().st_size > maximum:
        raise ValueError("input exceeds source bound")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("input bytes changed: " + str(path))
    return path, raw


def _json(pin, base):
    path, _ = _read(pin, base)
    value = read_json(path)
    _read(pin, base)
    return value


def _documents(request, base):
    _keys(request, ("schema_version", "task_id", "task", "source_capsules", "api_documents",
        "queries", "requested_quantities", "compatibility_groups", "max_source_bytes", "max_context_bytes", "max_steps"), "context request")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("context request schema_version must be integer 1")
    _text(request["task_id"], "task ID", 80); _text(request["task"], "scientific task")
    _integer(request["max_source_bytes"], "source bytes", maximum=MAX_SOURCE)
    _integer(request["max_context_bytes"], "context bytes", minimum=1024, maximum=MAX_CONTEXT)
    _integer(request["max_steps"], "scientific steps", maximum=MAX_STEPS)
    if type(request["source_capsules"]) is not list or len(request["source_capsules"]) > 8:
        raise ValueError("finite source capsule list required")
    if type(request["api_documents"]) is not list or len(request["api_documents"]) > 128:
        raise ValueError("finite API document list required")
    docs, pins, capsules = {}, [], []
    for index, pin in enumerate(request["source_capsules"]):
        path, _ = _read(pin, base, request["max_source_bytes"])
        capsule = analysis_sources.load_capsule(path)
        root, files = analysis_sources.source_files(capsule, path.parent)
        pins.append({"path": str(path), "sha256": pin["sha256"]})
        capsules.append({"pin": pins[-1], "source": capsule["source"],
            "dependencies": capsule["dependencies"], "dependency_review": capsule["dependency_review"]})
        for fact, file in zip(capsule["files"], files):
            bound = {"path": str(file), "sha256": fact["sha256"]}
            pins.append(bound)
            # Binary reference assets remain identified but never enter prompts.
            if file.suffix.lower() in {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".py", ".sh", ".md", ".txt", ".info", ".plot"}:
                _, raw = _read(bound, base, request["max_source_bytes"])
                docs[f"capsule{index}:{fact['path']}"] = {"pin": bound, "text": raw.decode(),
                    "language": "python" if file.suffix == ".py" else "text", "role": fact["role"],
                    "version": capsule["source"]["revision"], "dependencies": []}
    for row in request["api_documents"]:
        _keys(row, ("id", "pin", "language", "role", "version", "dependencies"), "API document")
        _text(row["id"], "document ID", 160)
        if row["id"] in docs or row["language"] not in {"python", "cpp", "text", "shell", "json"}:
            raise ValueError("duplicate API ID or unsupported extraction language")
        if row["role"] not in {"api", "example", "failure", "build", "runtime"}:
            raise ValueError("explicit API document role required")
        _text(row["version"], "source/runtime version attribution", 400)
        if type(row["dependencies"]) is not list or len(set(row["dependencies"])) != len(row["dependencies"]):
            raise ValueError("unique declared document dependencies required")
        path, raw = _read(row["pin"], base, request["max_source_bytes"])
        bound = {"path": str(path), "sha256": row["pin"]["sha256"]}
        pins.append(bound)
        docs[row["id"]] = {**deepcopy(row), "pin": bound, "text": raw.decode()}
    for requirement in _requirements(request['requested_quantities']):
        if 'read_requirement' in requirement:
            from . import data_read_outcomes
            pins.extend({'path':row['path'],'sha256':row['sha256']} for row in
                data_read_outcomes.requirement_pins(requirement['read_requirement'],base))
    if any('read_requirement' in q for q in request['requested_quantities']):
        pins=list({(p['path'],p['sha256']):p for p in pins}.values())
    if not docs or sum(Path(p["path"]).stat().st_size for p in pins) > request["max_source_bytes"]:
        raise ValueError("combined supplied corpus exceeds declared source bytes")
    for doc in docs.values():
        if set(doc["dependencies"]) - docs.keys():
            raise ValueError("unknown declared context dependency")
    return docs, pins, capsules


def input_pins(request, base):
    """Expand ordinary source capsules for the existing graph's explicit inputs."""
    return _documents(request, base)[1]


def step_pins(context, attempt, base):
    """Expose measured output pins across steps to the existing graph's reuse."""
    pins = input_pins(context["request"], base)
    for step in context["steps"]:
        pins.extend({key: row[key] for key in ("path", "sha256")} for row in step["outputs"])
    pins.extend(attempt["outputs"].values())
    return pins


def _definitions(text, symbol):
    tree = ast.parse(text)
    results = []
    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = prefix + child.name
                if symbol in {qualified, child.name}:
                    start = min([child.lineno] + [x.lineno for x in child.decorator_list])
                    results.append((start, child.end_lineno, "python-definition:" + qualified))
                visit(child, qualified + ".")
            else:
                visit(child, prefix)
    visit(tree, "")
    return results


def _spans(doc, query):
    text, symbol = doc["text"], query["symbol"]
    if query["mode"] == "definition" and doc["language"] == "python":
        return _definitions(text, symbol)
    lines = text.splitlines(keepends=True)
    token = symbol.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
    pattern = re.compile(r"(?<![\w])" + re.escape(token) + r"(?![\w])")
    python_blocks = []
    if doc["language"] == "python":
        # Preserve the surrounding execution unit rather than showing a call
        # stripped of local option construction/owners. This is syntax context,
        # not a proof of complete dynamic dependency or runtime semantics.
        tree = ast.parse(text)
        block_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For,
                       ast.AsyncFor, ast.With, ast.AsyncWith, ast.Try)
        python_blocks = [node for node in ast.walk(tree) if isinstance(node, block_types)]
    spans = []
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        if query["mode"] == "definition":
            # Explicit lexical declaration candidates, not a C++ semantic parser.
            before = line[:pattern.search(line).start()]
            if doc["language"] != "cpp" or not re.search(r"\w", before) or re.search(r"->|\.|=", before) or "(" in before:
                continue
            extraction = "cpp-declaration-window"
        else:
            extraction = "literal-occurrence-window"
        first, last = max(1, index - 3), min(len(lines), index + 14)
        containing = [n for n in python_blocks if n.lineno <= index + 1 <= n.end_lineno]
        functions = [n for n in containing if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if functions or containing:
            block = min(functions or containing, key=lambda n: n.end_lineno - n.lineno)
            first, last, extraction = block.lineno, block.end_lineno, "python-enclosing-execution-block"
        if spans and first <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], max(last, spans[-1][1]), extraction)
        else:
            spans.append((first, last, extraction))
    return spans


def _requirements(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise ValueError("one to 64 requested scientific quantities required")
    ids = set()
    for row in rows:
        _keys(row, ("id", "artifact", "pointer", "check", "meaning", *(['read_requirement'] if 'read_requirement' in row else [])), "requested quantity")
        if 'read_requirement' in row:
            from . import data_read_outcomes
            data_read_outcomes.validate_requirement(row['read_requirement'])
        for key in ("id", "artifact", "meaning"):
            _text(row[key], key, 2000)
        if row["id"] in ids:
            raise ValueError("duplicate requested quantity")
        ids.add(row["id"])
        if type(row["pointer"]) is not str or (row["pointer"] and not row["pointer"].startswith("/")):
            raise ValueError("JSON pointer required")
        check = row["check"]
        if type(check) is not dict or check.get("kind") not in {"finite", "exact", "record-census", "symbolic-record-census"}:
            raise ValueError("unsupported requested-quantity check")
        if check["kind"] == "finite":
            _keys(check, ("kind",), "finite quantity")
        elif check["kind"] == "exact":
            _keys(check, ("kind", "value"), "exact quantity")
            _digest(check["value"])
        else:
            field_key = 'text_fields' if check['kind'] == 'symbolic-record-census' else 'finite_fields'
            _keys(check, ("kind", "id_field", "expected_ids", field_key), "record quantity census")
            _text(check["id_field"], "record identity field", 200)
            if type(check["expected_ids"]) is not list or not check["expected_ids"] or len(check["expected_ids"]) > 4096:
                raise ValueError("explicit nonempty record denominator required")
            encoded = [_digest(x) for x in check["expected_ids"]]
            if len(set(encoded)) != len(encoded):
                raise ValueError("duplicate requested record identity")
            if (type(check[field_key]) is not list or not check[field_key]
                    or any(type(field) is not str or not field for field in check[field_key])
                    or len(set(check[field_key])) != len(check[field_key])):
                raise ValueError("unique declared record fields required")
    return deepcopy(rows)


def _groups(request, quantities):
    groups = request["compatibility_groups"]
    artifacts = {q["artifact"] for q in quantities}
    if type(groups) is not list or not 1 <= len(groups) <= len(artifacts):
        raise ValueError("explicit requested-artifact compatibility groups required")
    seen, ids = set(), set()
    for group in groups:
        _keys(group, ("id", "artifacts", "carryover", "basis"), "output compatibility group")
        _text(group["id"], "compatibility group ID", 80)
        _text(group["basis"], "declared compatibility basis", 2000)
        members = group["artifacts"]
        if group["id"] in ids or type(group["carryover"]) is not bool or type(members) is not list or not members:
            raise ValueError("invalid compatibility group")
        if len(set(members)) != len(members) or set(members) - artifacts or seen & set(members):
            raise ValueError("compatibility groups must cover each requested artifact once")
        seen.update(members); ids.add(group["id"])
    if seen != artifacts:
        raise ValueError("compatibility groups must cover each requested artifact once")
    return deepcopy(groups)


def _effective_outputs(groups, steps, supplied, attempt_id):
    effective = {}
    # Replay the small scientific context, preserving artifact origin. A declared
    # coupled group is an indivisible update; no old/new cross-arm splice.
    for step in [*steps, {"id": attempt_id, "outputs": supplied}]:
        outputs = {row["id"]: row for row in step["outputs"]}
        for group in groups:
            members = set(group["artifacts"])
            present = members & outputs.keys()
            if present and present != members:
                raise ValueError("coupled compatibility group must update all artifacts together")
            if not group["carryover"]:
                for identity in members:
                    effective.pop(identity, None)
            if present:
                for identity in members:
                    effective[identity] = {**outputs[identity], "source_step": step["id"],
                        "compatibility_group": group["id"]}
    return [{**row, "carried": row["source_step"] != attempt_id} for _, row in sorted(effective.items())]


def compile_context(request, base):
    """Compile named definitions/call examples; report missing and omitted context."""
    docs, pins, capsules = _documents(request, base)
    quantities = _requirements(request["requested_quantities"])
    groups = _groups(request, quantities)
    if type(request["queries"]) is not list or not 1 <= len(request["queries"]) <= 64:
        raise ValueError("finite nonempty API query list required")
    entries, resolutions, omissions, used, query_ids = [], [], [], 0, set()
    for query in request["queries"]:
        _keys(query, ("id", "symbol", "mode", "documents", "required"), "API query")
        _text(query["id"], "query ID", 80); _text(query["symbol"], "symbol", 160)
        if query["id"] in query_ids or query["mode"] not in {"definition", "occurrence"} or type(query["required"]) is not bool:
            raise ValueError("duplicate query or invalid extraction mode")
        query_ids.add(query["id"])
        if type(query["documents"]) is not list or len(set(query["documents"])) != len(query["documents"]) or set(query["documents"]) - docs.keys():
            raise ValueError("query references unknown or duplicate corpus IDs")
        selected = sorted(query["documents"] or docs)
        found, included = 0, 0
        for identity in selected:
            doc = docs[identity]
            for first, last, extraction in _spans(doc, query):
                found += 1
                excerpt = "".join(doc["text"].splitlines(keepends=True)[first-1:last])
                entry = {"query_id": query["id"], "document": identity, "pin": doc["pin"],
                    "source_version_attribution": doc["version"], "role": doc["role"],
                    "line_start": first, "line_end": last, "extraction": extraction,
                    "text": excerpt, "text_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "declared_dependencies": doc["dependencies"]}
                size = len(json.dumps(entry, ensure_ascii=False).encode())
                if used + size > request["max_context_bytes"]:
                    omissions.append({"query_id": query["id"], "document": identity,
                        "line_start": first, "line_end": last, "reason": "context byte budget; entire span omitted"})
                    continue
                entries.append(entry); used += size; included += 1
        resolutions.append({"id": query["id"], "symbol": query["symbol"], "required": query["required"],
            "matched_spans": found, "included_spans": included,
            "status": "complete-supplied-matches" if found and found == included else "omitted" if found else "not-found"})
    dependency_ids = sorted({x for row in entries for x in row["declared_dependencies"]})
    # Dependency documents are task-declared, not a claim of semantic closure.
    while dependency_ids:
        identity = dependency_ids.pop(0)
        if any(e.get("dependency_document") == identity for e in entries):
            continue
        doc = docs[identity]
        entry = {"dependency_document": identity, "pin": doc["pin"], "role": doc["role"],
            "source_version_attribution": doc["version"], "text": doc["text"],
            "text_sha256": hashlib.sha256(doc["text"].encode()).hexdigest()}
        size = len(json.dumps(entry).encode())
        if used + size > request["max_context_bytes"]:
            omissions.append({"document": identity, "reason": "declared dependency omitted by context byte budget"})
        else:
            entries.append(entry); used += size
            dependency_ids.extend(x for x in doc["dependencies"] if x not in dependency_ids)
    complete = not omissions and all(not r["required"] or r["status"] == "complete-supplied-matches" for r in resolutions)
    result = {"schema_version": 1, "kind": "scientific-step-context", "request": deepcopy(request),
        "request_sha256": _digest(request), "source_inventory": pins, "source_capsules": capsules,
        "api_resolution": resolutions, "context_entries": entries, "context_bytes": used,
        "omissions": omissions, "context_complete": complete, "requested_quantities": quantities,
        "compatibility_groups": groups, "effective_outputs": [],
        "steps": [], "measured_quantities": [], "unresolved_questions": [], "next_experiment": None,
        "quantity_completion": False, "execution_authorized": False, "physics_validated": False,
        "limits": ["C++/text spans are lexical context; no semantic closure or overload selection proof.",
            "Versions are attributed to supplied source or receipts, never inferred installed/runtime equality.",
            "Quantity completion is supplied-artifact goal completion, not native consumption or scientific acceptance.",
            "Cross-step output compatibility is explicitly declared by group, not inferred scientific composability."]}
    for pin in pins:
        _read(pin, base, request["max_source_bytes"])
    result["context_sha256"] = _digest(result)
    return result


def _pointer(value, pointer):
    if not pointer:
        return value
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise KeyError("noncanonical array index")
            value = value[int(key)]
        else:
            value = value[key]
    return value


def _finite(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def _check(value, check):
    if check["kind"] == "finite":
        return _finite(value), "finite numeric quantity required"
    if check["kind"] == "exact":
        return _digest(value) == _digest(check["value"]), "requested exact output differs"
    if type(value) is not list or len(value) != len(check["expected_ids"]):
        return False, "complete requested record denominator absent"
    observed = []
    for row in value:
        if type(row) is not dict or check["id_field"] not in row:
            return False, "record identity absent"
        observed.append(_digest(row[check["id_field"]]))
        if check['kind'] == 'symbolic-record-census':
            if (row.get('status') != 'delivered' or any(type(row.get(field)) is not str
                    or not row[field].strip() for field in check['text_fields'])):
                return False, 'complete delivered symbolic text required; correctness is not inferred'
        elif any(field not in row or not _finite(row[field]) for field in check['finite_fields']):
            return False, "requested finite record quantity absent"
    expected = [_digest(x) for x in check["expected_ids"]]
    return len(set(observed)) == len(observed) and set(observed) == set(expected), "requested record identity census differs"


def apply_step(context, attempt, base):
    """Read outputs, compute completion, retain questions and next experiment.

    The last bounded attempt can succeed: budget exhaustion is applied after
    requested quantity checks. A reported code success never replaces those checks.
    """
    initial = compile_context(context["request"], base)
    for key in initial:
        if key not in {"steps", "effective_outputs", "measured_quantities", "unresolved_questions", "next_experiment", "quantity_completion", "context_sha256"} and context.get(key) != initial[key]:
            raise ValueError("carried context source/API/request differs")
    prior = deepcopy(context); checksum = prior.pop("context_sha256")
    if _digest(prior) != checksum:
        raise ValueError("carried context content differs")
    if type(context["steps"]) is not list or len(context["steps"]) >= MAX_STEPS:
        raise ValueError("scientific step context exhausted")
    for step in context["steps"]:
        for output in step["outputs"]:
            _read({key: output[key] for key in ("path", "sha256")}, base)
    _keys(attempt, ("id", "outputs", "code_status", "actor_complete", "question", "next_experiment"), "step attempt")
    _text(attempt["id"], "attempt ID", 80)
    if attempt["id"] in {x["id"] for x in context["steps"]}:
        raise ValueError("duplicate scientific step attempt")
    if len(context["steps"]) >= initial["request"]["max_steps"]:
        raise ValueError("attempt limit reached before supplied step")
    if attempt["code_status"] not in {"success", "failure", "unknown"} or type(attempt["actor_complete"]) is not bool:
        raise ValueError("explicit code status and separate actor completion required")
    if type(attempt["outputs"]) is not dict or set(attempt["outputs"]) - {q["artifact"] for q in initial["requested_quantities"]}:
        raise ValueError("unknown requested-output artifact")
    outputs = []
    for identity, pin in attempt["outputs"].items():
        path, _ = _read(pin, base)
        outputs.append({"id": identity, "path": str(path), "sha256": pin["sha256"]})
    effective = _effective_outputs(initial["compatibility_groups"], context["steps"], outputs, attempt["id"])
    data = {row["id"]: _json({key: row[key] for key in ("path", "sha256")}, base) for row in effective}
    measured = []
    for requirement in initial["requested_quantities"]:
        source_value=data.get(requirement['artifact'])
        if (type(source_value) is dict and source_value.get('kind')=='root-stream-result'
                and 'read_outcomes' in source_value and 'read_requirement' not in requirement):
            raise ValueError('new typed ROOT acquisition requires the original source read requirement')
        passed, reason, value = False, "requested artifact absent", None
        try:
            value = _pointer(data[requirement["artifact"]], requirement["pointer"])
            passed, reason = _check(value, requirement["check"])
        except (KeyError, IndexError, TypeError):
            reason = "requested quantity absent"
        read_check=None
        if 'read_requirement' in requirement and requirement['artifact'] in data:
            from . import data_read_outcomes
            source=next(row for row in effective if row['id']==requirement['artifact'])
            # The original artifact must be the actual ROOT result, even when a
            # same-shaped scalar or array passes its numerical check.
            read_check=data_read_outcomes.consume({k:source[k] for k in ('path','sha256')},
                requirement['read_requirement'],base)
            if not read_check['passed']:
                passed,reason=False,read_check['reason']
        measured.append({"id": requirement["id"], "meaning": requirement["meaning"],
            "passed": passed, "value": value, "reason": None if passed else reason,
            **({'read_outcome':read_check} if 'read_requirement' in requirement else {})})
    complete = all(x["passed"] for x in measured)
    # Context readiness is reported independently: a measured output may exist
    # despite an unresolved API query, and failed code may have valid partial output.
    status = "quantities-complete" if complete else "budget-exhausted" if len(context["steps"]) + 1 == initial["request"]["max_steps"] else "revise"
    if not complete:
        _text(attempt["question"], "unresolved scientific question")
        _keys(attempt["next_experiment"], ("hypothesis", "change", "measurement", "if_supported", "if_not_supported"), "next experiment")
        for value in attempt["next_experiment"].values():
            _text(value, "prospective experiment component")
    result = deepcopy(context)
    step = {"id": attempt["id"], "code_status_reported": attempt["code_status"],
        "actor_complete_reported": attempt["actor_complete"], "outputs": outputs,
        "effective_output_sources": effective,
        "quantity_checks": measured, "status": status,
        "question": None if complete else attempt["question"],
        "next_experiment": None if complete else deepcopy(attempt["next_experiment"])}
    result["steps"].append(step)
    result.update(effective_outputs=effective, measured_quantities=measured, quantity_completion=complete,
        unresolved_questions=[] if complete else [{"question": attempt["question"], "missing_quantities": [x["id"] for x in measured if not x["passed"]]}],
        next_experiment=step["next_experiment"])
    for row in effective:
        _read({key: row[key] for key in ("path", "sha256")}, base)
    result.pop("context_sha256"); result["context_sha256"] = _digest(result)
    return result


def persist_context(path, context, *, expected_parent_sha256=None):
    """Use existing state primitives for a compact, restartable scientific context."""
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("ordinary context path required")
    check = deepcopy(context); sha = check.pop("context_sha256")
    if _digest(check) != sha:
        raise ValueError("context checksum differs")
    with file_lock(path.with_suffix(".lock")):
        if path.exists():
            prior = read_json(path)
            if expected_parent_sha256 is None or prior["context_sha256"] != expected_parent_sha256:
                raise ValueError("explicit unchanged parent context required")
            if len(context["steps"]) != len(prior["steps"]) + 1 or context["steps"][:-1] != prior["steps"] or context["request_sha256"] != prior["request_sha256"]:
                raise ValueError("context update must append exactly one scientific step")
        elif expected_parent_sha256 is not None:
            raise ValueError("parent context missing")
        atomic_json(path, context)
    return {"path": str(path.absolute()), "sha256": analysis_sources.digest(path), "context_sha256": sha}
