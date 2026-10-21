"""Machine checks of decision-justification anchors (RDJ §5.3).

Each anchor kind has a mandatory binding. ``verify`` sets ``external``,
``generated`` or ``invalid``; the proposer never sets it. ``external`` means the
anchor resolves to something that exists independently of the actors in the case:
a current execution receipt from a recognized tool that the stage supervisor registered
in custody, an input recorded in RAVEL's custody snapshot, user text RAVEL recorded, or
a shipped invariant. Model outputs, files an agent wrote, RAVEL's own request files,
files of unknown provenance, research-board content (under the case's ``board_head``)
and review or integrity verdicts (an opinion record, never evidence) are ``generated``.
Broker tool receipts stay ``generated`` until their producers' append-only ledgers
can be verified. Retrieval anchors use the acquisition ledger and exact captured bytes.
An anchor at the path of the action under decision, or from
the stage that produced it, is circular and ``invalid``.

The reviewer is shown the value read from the verified bytes, never a value the
proposer typed; a proposer value that differs from the bytes is ``invalid``.

The self-grounding rule, the circularity rule, the authoritative-practice rule for
claims that recommend an analysis choice, and conflict detection live here too.
"""
from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from . import rdj_custody
from .decision_case import jdigest
from .diagnostic_plan import pointer, read_json

DATA = Path(__file__).resolve().parents[1] / "data"
POLICY = DATA / "rdj" / "policy.json"
INVARIANTS = DATA / "rdj" / "invariants.json"
TOOL_KINDS = ("tool_output", "measurement")
RETRIEVAL_KINDS = ("retrieved_document", "external_fact")
MAX_PATHS = 4096
SHOWN_TEXT = 2000
MAX_RETRIEVED_BYTES = 16 << 20
WRITE_LOG = "agent-audit/writes.jsonl"


class AnchorError(ValueError):
    """An anchor that cannot be bound (invalid)."""


class Generated(ValueError):
    """An anchor whose bytes come from inside the case or have unknown provenance (generated)."""


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def policy():
    return read_json(POLICY)


def policy_pin():
    return {"path": str(POLICY), "sha256": sha256_file(POLICY)}


def _keys(value, required, optional=(), label="binding"):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise AnchorError(f"{label} requires {sorted(required)}" + (f" (optional {sorted(optional)})" if optional else ""))


def inside(rundir, value):
    """A regular, non-symlinked file inside the run; returns (path, run-relative name)."""
    if not isinstance(value, str) or not value:
        raise AnchorError("anchor path must be a nonempty string")
    root = Path(rundir).resolve()
    raw = Path(value)
    if raw.is_absolute():
        for base in (Path(rundir).absolute(), root):
            if raw.is_relative_to(base):
                raw = raw.relative_to(base)
                break
        else:
            raise AnchorError(f"anchor file escapes the run: {value}")
    if ".." in raw.parts:
        raise AnchorError(f"anchor file escapes the run: {value}")
    path = root
    for part in raw.parts:
        path = path / part
        if path.is_symlink():
            raise AnchorError(f"anchor file is or sits under a symlink: {value}")
    if not path.is_file():
        raise AnchorError(f"anchor file is absent: {value}")
    return path, raw.as_posix()


_inside = inside


def _matches_hash(path, sha, label):
    if sha256_file(path) != sha:
        raise AnchorError(f"{label} bytes differ from the bound sha256")


def _shown(text):
    return text if len(text) <= SHOWN_TEXT else text[:SHOWN_TEXT] + f"... [{len(text)} characters]"


def _located(path, locator):
    """``(value compared, value shown)`` read from the bytes. An empty locator reads the whole
    file: text is compared in full and shown truncated; binary content is its size and digest."""
    if locator == "":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            value = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            return value, value
        return text, _shown(text)
    value = pointer(read_json(path), locator)
    return value, value


def _same_value(anchor, observed):
    full, shown = observed if isinstance(observed, tuple) else (observed, observed)
    if anchor.get("value") is not None and jdigest(anchor["value"]) != jdigest(full):
        raise AnchorError("the recorded value differs from the value in the verified bytes")
    return shown


def verdict_record(path, rel):
    """Whether a file is a review or integrity verdict: an opinion record, never evidence."""
    rules = policy()["verdict_records"]
    if any(fnmatch.fnmatchcase(Path(rel).name, p) for p in rules["path_patterns"]):
        return True
    try:
        if path.stat().st_size > 1 << 24:
            return False
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and value.get("kind") in rules["kinds"]


def _provenance(rel, context, path=None):
    if rel.startswith("rdj/"):
        raise Generated(f"{rel} is a decision-justification record, not evidence")
    if context and rel in set(context.get("generated", ())):
        raise Generated(f"{rel} was written by an agent session or a model call")
    for directory in (context or {}).get("generated_dirs", ()):
        if rel == directory or rel.startswith(directory.rstrip("/") + "/"):
            raise Generated(f"{rel} is research-board content under the case's board_head, not evidence")
    if path is not None and verdict_record(path, rel):
        raise Generated(f"{rel} is a review or integrity verdict, an opinion record and not evidence")


def _circular(path, sha, context):
    context = context or {}
    root = Path(context["rundir"]).resolve() if context.get("rundir") else None
    for pin in context.get("action_pins", ()):
        pinned = Path(pin["path"])
        pinned = pinned if pinned.is_absolute() or root is None else root / pinned
        if pinned.resolve() == path.resolve():
            raise AnchorError("circular: the anchor is the output of the action under decision")


# ---------------------------------------------------------------- producers

def _python(argv0):
    return argv0 == sys.executable or bool(re.fullmatch(r"python(\d+(\.\d+)?)?", Path(argv0).name))


def _module_file(module):
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    return Path(spec.origin).resolve() if spec is not None and spec.origin and spec.origin.endswith(".py") else None


def _module_tool(module, prefixes):
    return any(module.startswith(p) if p.endswith(".") else module == p for p in prefixes) \
        and _module_file(module) is not None


def _shadowed(module, cwd):
    """Whether ``python -m module`` run in ``cwd`` would import a file there instead of RAVEL's
    (``-m`` puts the working directory first on the import path)."""
    if not cwd:
        return True
    base = Path(cwd)
    parts = module.split(".")
    for depth in range(1, len(parts) + 1):
        stem = base.joinpath(*parts[:depth])
        if stem.with_suffix(".py").exists() or (stem / "__init__.py").exists() or \
                (depth < len(parts) and stem.is_dir()):
            return True
    return False


def _native(command0, names):
    """A native tool: a listed name invoked bare (resolved on the native environment's path), or
    any executable inside RAVEL's native build. A listed name at another path is not one."""
    path = Path(command0)
    if len(path.parts) == 1:
        return command0 if command0 in names else None
    resolved = path.resolve()
    for variable in ("RAVEL_NATIVE_BIN", "RAVEL_NATIVE_BUILD"):
        base = os.environ.get(variable)
        if base and resolved.is_relative_to(Path(base).resolve()):
            return resolved.name
    return None


def _snapshot_sha(snapshot, path):
    entry = (snapshot or {}).get(str(path))
    for row in (entry or {}).get("files", ()):
        if row.get("name") == ".":
            return row.get("sha256")
    return None


def producer(rundir, record):
    """Positive classification of what produced a stage's outputs, or None.

    ``("module", name)``: a RAVEL tool module run as ``python -m`` from a working directory
    that does not shadow it (and, when the execution record carries ``module_origin`` and
    ``module_sha256``, whose recorded origin is RAVEL's file); ``("native", name)``: a native
    tool inside RAVEL's native build; ``("authored_script", rel, sha256)``: a script inside
    the run that the stage pinned as an input. Anything else (agent CLIs, model calls,
    unknown commands, a tool name outside the native build) is not a tool.
    """
    rules = policy()["tool_producers"]
    command = [str(t) for t in record.get("command") or []]
    if not command:
        return None
    if _python(command[0]) and len(command) >= 3:
        from ravel.paths import module_command
        # The package's exact launcher is the source-defined module transport.
        # A copied or similarly named script never inherits this recognition.
        bootstrap = module_command('ravel.physics.science_worker')[1]
        if Path(command[1]).is_absolute() and Path(command[1]).resolve() == Path(bootstrap).resolve():
            command = [command[0], '-m', command[2], *command[3:]]
    if _python(command[0]) and len(command) >= 3 and command[1] == "-m":
        module = command[2]
        if not _module_tool(module, rules["python_module_prefixes"]) or _shadowed(module, record.get("cwd")):
            return None
        if "module_origin" in record or "module_sha256" in record:
            origin = _module_file(module)
            if Path(str(record.get("module_origin"))).resolve() != origin \
                    or record.get("module_sha256") != sha256_file(origin):
                return None
        return ("module", module)
    if _python(command[0]) and len(command) >= 2 and command[1].endswith(".py"):
        script = Path(command[1])
        script = (script if script.is_absolute() else Path(record.get("cwd") or rundir) / script).resolve()
        for name in policy()["measurement_validators"].values():
            if _module_file(name) == script:
                return ("module", name)
        root = Path(rundir).resolve()
        if not script.is_relative_to(root):
            return None
        rel = script.relative_to(root).as_posix()
        pinned = _snapshot_sha(record.get("input_snapshot"), script)
        if pinned is None or not any(rel.startswith(p) for p in rules["authored_script_prefixes"]):
            return None
        return ("authored_script", rel, pinned)
    name = _native(command[0], rules["native_tools"])
    return ("native", name) if name is not None else None


class StageCheck:
    """One execution validation session for one verification pass: a single runtime census
    serves every stage anchor checked in the pass, and the session's ending check covers them all."""

    def __init__(self, rundir):
        self.rundir, self.session, self.state, self.results = Path(rundir), None, None, {}

    def errors(self, stage):
        from . import execution
        if stage not in self.results:
            try:
                if self.session is None:
                    self.state = execution.load_execution(self.rundir)
                    self.session = execution._validation_session(self.rundir, self.state)
                self.results[stage] = execution.stage_errors(self.rundir, stage, self.state, _session=self.session)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.results[stage] = [f"stage {stage} evidence unavailable: {exc}"]
        return self.results[stage]

    def close(self):
        """Errors from the session's ending check (files that changed while being validated)."""
        if self.session is None:
            return []
        try:
            return list(self.session.finish())
        finally:
            self.session.close()


def verify_all(anchors, rundir, *, context=None):
    """``{anchor id: (status, reason, observed)}`` for one verification pass."""
    checker = StageCheck(rundir)
    context = {**(context or {}), "stages": checker}
    try:
        results = {a["id"]: verify_full(a, rundir, context=context) for a in anchors}
    finally:
        ending = checker.close()
    if ending:
        for anchor in anchors:
            if anchor["kind"] in TOOL_KINDS and results[anchor["id"]][0] == "external":
                results[anchor["id"]] = ("invalid", "execution evidence changed during validation: " + "; ".join(ending), None)
    return results


def stage_receipt(rundir, receipt_id, context=None):
    """The record of a current stage receipt ``stage:<name>:<attempt_id>``: present in the
    execution ledger, registered in custody by the stage supervisor and valid by
    ``execution.stage_errors``. Raises ``Generated`` when unregistered, ``AnchorError`` otherwise."""
    from . import execution
    try:
        _, stage, attempt = receipt_id.split(":", 2)
    except (AttributeError, ValueError):
        raise AnchorError("stage receipt id must be stage:<name>:<attempt_id>") from None
    record = execution.load_execution(rundir)["stages"].get(stage)
    if not isinstance(record, dict) or record.get("attempt_id") != attempt:
        raise AnchorError(f"no execution receipt {receipt_id}")
    checker = (context or {}).get("stages")
    errors = checker.errors(stage) if checker is not None else execution.stage_errors(rundir, stage)
    if errors:
        raise AnchorError(f"execution receipt {receipt_id} is not current: " + "; ".join(errors))
    if not rdj_custody.stage_receipt_registered(rundir, stage, attempt, record):
        raise Generated(f"execution receipt {receipt_id} was not registered by the stage supervisor")
    return record


def _stage_receipt(rundir, receipt_id, kind, binding, context):
    """``stage:<name>:<attempt_id>`` registered and current; the output and producer bind the anchor."""
    from . import execution
    record = stage_receipt(rundir, receipt_id, context)
    root = Path(rundir).resolve()
    pinned = {Path(p["path"]) if Path(p["path"]).is_absolute() else root / p["path"]
              for p in (context or {}).get("action_pins", ())}
    for value in record.get("outputs", ()):
        out = execution.resolve_path(root, value, output=True)
        if any(p.resolve() == out or p.resolve().is_relative_to(out) for p in pinned):
            raise AnchorError("circular: the anchor comes from the stage that produced the action under decision")
    output, _ = inside(rundir, binding["output_path"])
    listed = False
    for key, entry in (record.get("output_snapshot") or {}).items():
        for row in entry.get("files", ()):
            candidate = Path(key) if row["name"] == "." else Path(key) / row["name"]
            if candidate.resolve() == output:
                listed = row["sha256"] == binding["sha256"]
    if not listed:
        raise AnchorError("the receipt does not list this output with this sha256")
    made_by = producer(rundir, record)
    if kind == "measurement":
        module = policy()["measurement_validators"].get(binding.get("validator_id"))
        path = _module_file(module) if module else None
        if path is None or made_by != ("module", module):
            raise AnchorError("the receipt's producer is not the named registered validator")
        if binding.get("validator_sha256") != sha256_file(path):
            raise AnchorError("the validator's code differs from the bound validator_sha256")
    if made_by is None:
        raise Generated("the producing command is not a recognized tool (a model call or unknown command)")
    if made_by[0] == "authored_script":
        if binding.get("script_sha256") != made_by[2]:
            raise AnchorError("an authored-script output binds the script_sha256 the stage pinned")
    elif "script_sha256" in binding:
        raise AnchorError("script_sha256 applies only to an authored script")


def _tool(anchor, rundir, context):
    binding = anchor["binding"]
    optional = ("validator_id", "validator_sha256", "script_sha256")
    _keys(binding, ("receipt_id", "output_path", "sha256"), optional, anchor["kind"] + " binding")
    if anchor["kind"] == "measurement" and not {"validator_id", "validator_sha256"} <= set(binding):
        raise AnchorError("a measurement binds validator_id and validator_sha256")
    path, rel = inside(rundir, binding["output_path"])
    _circular(path, binding["sha256"], context)
    receipt = binding["receipt_id"]
    if not isinstance(receipt, str):
        raise AnchorError("receipt id must be a string")
    if not receipt.startswith("stage:"):
        raise Generated("broker receipts are not trusted until the broker ledger can verify them")
    _provenance(rel, context, path)
    _stage_receipt(rundir, receipt, anchor["kind"], binding, context)
    _matches_hash(path, binding["sha256"], "tool output")
    return _same_value(anchor, _located(path, anchor["locator"]))


def verify_pin(rundir, pin, *, context=None):
    """``external`` when a ``{path, sha256}`` pin is an external input or an output listed by a
    registered, current stage receipt of a recognized tool; else ``generated`` or ``invalid``."""
    from . import execution
    if type(pin) is not dict or set(pin) != {"path", "sha256"}:
        return "invalid"
    if verify({"kind": "input_artifact", "binding": pin, "locator": ""}, rundir, context=context) == "external":
        return "external"
    try:
        _, rel = inside(rundir, pin["path"])
        stages = execution.load_execution(rundir)["stages"]
    except (AnchorError, OSError, ValueError, KeyError, TypeError):
        return "invalid"
    best = "generated"
    root = Path(rundir).resolve()
    for name, record in stages.items():
        if not isinstance(record, dict) or not record.get("attempt_id"):
            continue
        for key, entry in (record.get("output_snapshot") or {}).items():
            for row in (entry or {}).get("files", ()):
                candidate = Path(key) if row.get("name") == "." else Path(key) / row.get("name", "")
                candidate = candidate if candidate.is_absolute() else root / candidate
                if candidate.resolve() == root / rel and row.get("sha256") == pin["sha256"]:
                    anchor = {"kind": "tool_output", "locator": "", "binding": {
                        "receipt_id": f"stage:{name}:{record['attempt_id']}", "output_path": rel,
                        "sha256": pin["sha256"]}}
                    status = verify(anchor, rundir, context=context)
                    if status == "external":
                        return status
                    best = "invalid" if status == "invalid" else best
    return best


def _input(anchor, rundir, context):
    binding = anchor["binding"]
    _keys(binding, ("path", "sha256"), label="input_artifact binding")
    path, rel = inside(rundir, binding["path"])
    _circular(path, binding["sha256"], context)
    _provenance(rel, context, path)
    snapshot = (context or {}).get("input_snapshot")
    if snapshot is None:
        raise Generated("no RAVEL input snapshot precedes this case")
    if snapshot.get(rel) != binding["sha256"]:
        raise Generated(f"{rel} is not an external input in RAVEL's snapshot before the case "
                        "(written later, by an agent, or by RAVEL itself)")
    _matches_hash(path, binding["sha256"], "input artifact")
    return _same_value(anchor, _located(path, anchor["locator"]))


def _retrieved(anchor, rundir, context):
    binding = anchor["binding"]
    if anchor["kind"] == "external_fact" and "record_id" in binding:
        _keys(binding, ("record_id", "file"), label="reference-data binding")
        observed = _input({**anchor, "kind": "input_artifact", "binding": binding["file"]}, rundir, context)
        return observed
    _, excerpt = _retrieval(anchor, rundir, context)
    return _same_value(anchor, (excerpt, _shown(excerpt)))


def _retrieval(anchor, rundir, context):
    """Authenticated acquisition identity and a UTF-8 excerpt at byte offsets.

    Only the exact outputs of a retrieval registered outside the worker sandbox
    can cross the generated-file boundary. A citation and a public receipt alone
    do not authenticate either the source identity or its bytes.
    """
    from . import broker
    binding = anchor["binding"]
    _keys(binding, ("acquisition_receipt", "content_sha256", "excerpt_span", "excerpt_sha256"),
          ("source_reference",), label=anchor["kind"] + " binding")
    receipt_pin = binding["acquisition_receipt"]
    _keys(receipt_pin, ("path", "sha256"), label="acquisition receipt pin")
    try:
        receipt = broker.verify_acquisition_receipt(rundir, receipt_pin)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Generated(f"acquisition ledger cannot verify retrieval: {exc}") from None
    if receipt.get("exit_status") != 0:
        raise AnchorError("acquisition did not finish successfully")
    candidates = [pin for pin in receipt["output_pins"] if pin["sha256"] == binding["content_sha256"]]
    if len(candidates) != 1:
        raise AnchorError("content_sha256 must identify exactly one acquired output")
    path = broker.locate(rundir, candidates[0]["path"])
    _circular(path, binding["content_sha256"], context)
    rel = candidates[0]["path"]
    # Acquisition custody, rather than the worker output directory, determines
    # provenance here. Board and opinion records still cannot become evidence.
    _provenance(rel, {**(context or {}), "generated": []}, path)
    if anchor["locator"] != "":
        raise AnchorError("a retrieved excerpt is located by its byte span, not a locator")
    if path.stat().st_size > MAX_RETRIEVED_BYTES:
        raise AnchorError("acquired content exceeds the anchor byte limit")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding["content_sha256"]:
        raise AnchorError("acquired content changed during verification")
    span = binding["excerpt_span"]
    _keys(span, ("start", "end"), label="excerpt byte span")
    start, end = span["start"], span["end"]
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(raw)):
        raise AnchorError("excerpt byte span lies outside acquired content")
    excerpt = raw[start:end]
    if hashlib.sha256(excerpt).hexdigest() != binding["excerpt_sha256"]:
        raise AnchorError("acquired excerpt differs from excerpt_sha256")
    if broker.verify_acquisition_receipt(rundir, receipt_pin) != receipt:
        raise AnchorError("acquisition evidence changed during verification")
    return receipt["source"], excerpt.decode("utf-8")


def _practice_reference(anchor, rundir, context):
    """Read a source classification from independent input bytes, never a citation.

    The reference descriptor must predate the case in custody (or be a vouched
    acquisition in its snapshot), bind the acquired source identity and complete
    content digest, and name a policy-recognized scientific reference category.
    It establishes provenance and declared source type, not scientific acceptance
    or applicability to the claim; those remain review obligations.
    """
    pin = anchor["binding"].get("source_reference")
    if pin is None:
        return False
    _keys(pin, ("path", "sha256"), label="scientific reference pin")
    path, _ = inside(rundir, pin["path"])
    if path.stat().st_size > SHOWN_TEXT:
        raise AnchorError("scientific reference descriptor exceeds its byte limit")
    _input({"kind": "input_artifact", "binding": pin, "locator": "", "value": None}, rundir, context)
    reference = read_json(path)
    _keys(reference, ("schema_version", "kind", "source_class", "source", "content_sha256"),
          label="scientific reference descriptor")
    source, excerpt = _retrieval(anchor, rundir, context)
    _same_value(anchor, (excerpt, _shown(excerpt)))
    _matches_hash(path, pin["sha256"], "scientific reference descriptor")
    return (type(reference["schema_version"]) is int and reference["schema_version"] == 1
            and reference["kind"] == "scientific-practice-reference"
            and reference["source_class"] in policy()["practice_source_classes"]
            and reference["source"] == source
            and reference["content_sha256"] == anchor["binding"]["content_sha256"])


def _requirement(anchor, rundir, context):
    binding = anchor["binding"]
    _keys(binding, ("source", "sha256", "start", "end", "text"), ("path",), "user_requirement binding")
    source = binding["source"]
    if source == "prompt":
        if "path" in binding:
            raise AnchorError("a prompt span binds the original task prompt, not a file named by the proposer")
        rel = rdj_custody.TASK_CONTRACT
    elif source == "checkin1_response":
        rel = binding.get("path", rdj_custody.CI1_RESPONSE)
    elif source == "user_steering":
        rel = binding.get("path", "")
    else:
        raise AnchorError("user_requirement source must be prompt, checkin1_response or user_steering")
    if anchor["locator"] != "":
        raise AnchorError("a user_requirement is located by its span, not a locator")
    try:
        whole, digest, _ = rdj_custody.user_text(rundir, source, rel)
    except rdj_custody.CustodyError as exc:
        raise Generated(str(exc)) from None
    except (OSError, ValueError) as exc:
        raise AnchorError(f"RAVEL-written request files never qualify; {exc}") from None
    _provenance(rel, context)
    if digest != binding["sha256"]:
        raise AnchorError("the user text differs from the bound sha256")
    start, end = binding["start"], binding["end"]
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(whole)):
        raise AnchorError("requirement span lies outside the user text")
    if whole[start:end] != binding["text"]:
        raise AnchorError("requirement text does not equal source[start:end]")
    return _same_value(anchor, binding["text"])


def invariant_rows():
    return {row["id"]: row for row in read_json(INVARIANTS)["invariants"]}


def _invariant(anchor, rundir, context):
    binding = anchor["binding"]
    _keys(binding, ("invariant_id", "registry_sha256"), label="invariant binding")
    if sha256_file(INVARIANTS) != binding["registry_sha256"]:
        raise AnchorError("invariant registry digest differs")
    row = invariant_rows().get(binding["invariant_id"])
    if row is None:
        raise AnchorError("unknown invariant id")
    if anchor["locator"] != "":
        raise AnchorError("an invariant is located by its id, not a locator")
    return _same_value(anchor, row["statement"])


CHECKS = {"tool_output": _tool, "measurement": _tool, "input_artifact": _input,
          "retrieved_document": _retrieved, "external_fact": _retrieved,
          "user_requirement": _requirement, "invariant": _invariant}


def verify_full(anchor, rundir, *, context=None):
    """Return ``(status, reason, observed value)``; status is external, generated or invalid."""
    check = CHECKS.get(anchor.get("kind") if isinstance(anchor, dict) else None)
    if check is None:
        return "invalid", f"unknown anchor kind {anchor.get('kind') if isinstance(anchor, dict) else anchor!r}", None
    try:
        observed = check(anchor, Path(rundir), context)
    except Generated as exc:
        return "generated", str(exc), None
    except (AnchorError, OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError) as exc:
        return "invalid", str(exc) or type(exc).__name__, None
    return "external", None, observed


def verify_detail(anchor, rundir, *, context=None):
    """Return ``(status, reason)``; status is external, generated or invalid."""
    return verify_full(anchor, rundir, context=context)[:2]


def verify(anchor, rundir, *, context=None):
    """``external`` | ``generated`` | ``invalid``."""
    return verify_full(anchor, rundir, context=context)[0]


def generated_paths(rundir):
    """Run-relative files written by agent sessions or model calls.

    Sources: the agent write log ``agent-audit/writes.jsonl`` (one ``{path, sha256,
    session_id}`` line per write, when the run has one) and every file a model worker
    produced under ``agent-work/<node>/<attempt>/`` (outputs, scratch, final record).
    """
    root = Path(rundir).resolve()
    found = set()
    log = root / WRITE_LOG
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = Path(json.loads(line)["path"])
            if raw.is_absolute():
                if not raw.resolve().is_relative_to(root):
                    continue
                raw = raw.resolve().relative_to(root)
            found.add(raw.as_posix())
    work = root / "agent-work"
    if work.is_dir():
        for path in work.rglob("*"):
            parts = path.relative_to(work).parts
            if path.is_file() and len(parts) >= 3 and (parts[2] in ("outputs", "scratch") or parts[2] == "final.json"):
                found.add(path.relative_to(root).as_posix())
    return found


# ---------------------------------------------------------------- case-level rules

def _graph(case):
    nodes = {n["id"]: n for n in case["nodes"]}
    out = {n: [] for n in nodes}
    for edge in case["edges"]:
        out[edge["parent"]].append(edge)
    return nodes, out


def material_paths(case, *, limit=MAX_PATHS):
    """Every root-to-leaf path through material ``supports`` edges, as (node ids, edges).

    The number of paths is counted first in linear time, so a wide hand-built DAG is
    refused before any enumeration.
    """
    nodes, out = _graph(case)
    root = case["proposal"]["node_id"]

    def children(node_id):
        return [e for e in out[node_id] if e["relation"] == "supports" and nodes[e["child"]]["material"]]
    count = {}

    def paths_from(node_id, stack=()):
        if node_id in count:
            return count[node_id]
        if node_id in stack:
            raise ValueError("cyclic decision case")
        below = children(node_id)
        count[node_id] = 1 if not below else sum(paths_from(e["child"], stack + (node_id,)) for e in below)
        return count[node_id]
    if paths_from(root) > limit:
        raise ValueError(f"decision case has more than {limit} material paths")
    paths = []

    def walk(node_id, ids, edges):
        below = children(node_id)
        if not below:
            paths.append((ids, edges))
        for edge in below:
            walk(edge["child"], ids + [edge["child"]], edges + [edge])
    walk(root, [root], [])
    return paths


def self_grounded_paths(case, statuses):
    """Paths whose leaf carries no ``external`` anchor (RDJ §5.3 self-grounding rule)."""
    nodes, _ = _graph(case)
    return [ids for ids, _ in material_paths(case)
            if not any(statuses.get(a) == "external" for a in nodes[ids[-1]]["anchors"])]


def practice_anchor(anchor, status, *, rundir=None, context=None):
    """Practice authority from recorded user text, invariants or verified reference provenance.

    Authority is never a source class the proposer puts on the anchor. Reference
    categories come from independent pinned input bytes joined to acquisition custody."""
    if status != "external":
        return False
    if anchor["kind"] == "user_requirement":
        return True
    if anchor["kind"] == "invariant":
        return bool(invariant_rows().get(anchor["binding"]["invariant_id"], {}).get("practice"))
    if anchor["kind"] in RETRIEVAL_KINDS and rundir is not None and "acquisition_receipt" in anchor["binding"]:
        try:
            return _practice_reference(anchor, rundir, context)
        except (AnchorError, Generated, OSError, ValueError, KeyError, TypeError, UnicodeError):
            return False
    return False


def exploratory_nodes(case, statuses, marked=(), *, rundir=None, context=None):
    """Claims recommending an analysis choice (declared, derived or marked by a reviewer)
    without an authoritative-practice anchor in their support."""
    nodes, out = _graph(case)
    anchors = {a["id"]: a for a in case["anchors"]}
    memo = {}

    def grounded(node_id):
        if node_id not in memo:
            memo[node_id] = False
            memo[node_id] = any(practice_anchor(anchors[a], statuses.get(a), rundir=rundir, context=context)
                                for a in nodes[node_id]["anchors"]) \
                or any(grounded(e["child"]) for e in out[node_id] if e["relation"] == "supports")
        return memo[node_id]
    marked = set(marked)
    return [n for n, node in nodes.items() if (node["recommends_choice"] or n in marked) and not grounded(n)]


def quantity_keys(anchor):
    """What an anchor measures. The full JSON-pointer locator always identifies it (so a label
    cannot hide a conflict, and ``/signal/rate`` is not ``/background/rate``); a proposer's
    ``quantity`` label adds a key and can only join anchors, never separate them."""
    keys_ = set()
    locator = anchor.get("locator") or ""
    if locator.strip("/"):
        keys_.add("locator:" + locator.rstrip("/"))
    if anchor.get("quantity"):
        keys_.add("label:" + str(anchor["quantity"]))
    return keys_


def quantity_of(anchor):
    """One readable name of what an anchor measures (its label, else its locator), or None."""
    return anchor.get("quantity") or (anchor.get("locator") or "").rstrip("/") or None


def conflicting_nodes(case, statuses, tolerance, observed):
    """Nodes holding external anchors that locate the same quantity with incompatible values."""
    by_quantity, owners = {}, {}
    for node in case["nodes"]:
        for a in node["anchors"]:
            owners.setdefault(a, set()).add(node["id"])
    for anchor in case["anchors"]:
        value = observed.get(anchor["id"])
        if statuses.get(anchor["id"]) == "external" and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            for key in quantity_keys(anchor):
                by_quantity.setdefault(key, []).append((anchor, float(value)))
    conflicted = set()
    for rows in by_quantity.values():
        values = [v for _, v in rows]
        scale = max(abs(v) for v in values) or 1.0
        if max(values) - min(values) > tolerance * scale:
            for anchor, _ in rows:
                conflicted |= owners.get(anchor["id"], set())
    return sorted(conflicted)


def evidence_source(anchor):
    """Content identity for evidence counting and common-source detection.

    New paths, producer receipts or acquisition routes cannot turn identical
    bytes into additional evidence. Distinct content is necessary here, but does
    not establish independent scientific provenance or methods.
    """
    binding = anchor.get("binding") or {}
    if anchor["kind"] in (*TOOL_KINDS, "input_artifact"):
        return ("content", binding.get("sha256"))
    if anchor["kind"] == "external_fact" and isinstance(binding.get("file"), dict):
        return ("content", binding["file"].get("sha256"))
    if anchor["kind"] in RETRIEVAL_KINDS:
        return ("content", binding.get("content_sha256"))
    return None


def describe(anchor, observed=None):
    """What an edge reviewer is shown about an anchor: the value read from its verified bytes,
    its binding identity, and the script digest for authored scripts."""
    shown = {k: anchor[k] for k in ("id", "kind", "locator", "verified")}
    shown["value"] = observed if anchor.get("verified") == "external" else None
    binding = anchor["binding"]
    for key in ("receipt_id", "output_path", "validator_id", "validator_sha256", "script_sha256", "source", "text",
                "invariant_id", "path"):
        if key in binding:
            shown[key] = binding[key]
    if anchor["kind"] in RETRIEVAL_KINDS:
        for key in ("acquisition_receipt", "content_sha256", "excerpt_span", "excerpt_sha256", "source_reference"):
            if key in binding:
                shown[key] = binding[key]
    return json.loads(json.dumps(shown))
