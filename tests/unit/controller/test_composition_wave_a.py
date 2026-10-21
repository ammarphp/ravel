"""Wave-A exit gate: one inert autonomous run on the real controller composition.

The coordinator treats this file as the wave-A gate. One run is configured through the operator's
own channel (``ravel operator init``: autonomous mode, machine-resolved check-ins, the default
budgets, restricted sources and the run's agent preferences), started from request bytes and driven
unattended with every in-process seam of the controller refused (``testing.seams(False,
controller=True)``). Nothing is substituted: the ledger, authority, instructions, confinement,
judgment and sink are the installed packages, and every worker session goes through the real step
graph, the restricted CLI worker transport, the OS sandbox and the confinement package's inventory
probe. The worker executable is inert: it reads the RAVEL-built packet, talks to the broker MCP
server and writes the step's declared outputs from its own inputs; it never calls a model, a
provider or the network, and no native science runs.

Two things a test process cannot provide are stood in, each at its source: the identity of an
installed, read-only RAVEL (a test runs from a checkout) and the location of the issuer's private home
(inside the test's lock domain instead of the account's). The worker transport is qualified as the
operator qualifies it: the real transport probe, then the real qualifier's live conformance run of the
inert executable in the sandbox, whose passed record is retained in the run's own store (the only
qualification a controller seat counts).

The gate's milestones, in the order the run reaches them (first form; the rc1 form adds an
authenticated accepted delivery):

1. ``ledger.gate(store, 'intake->route_select') == []``;
2. ``ledger.gate(store, 'plan_review->checkin1') == []``;
3. CHECK-IN 1 resolved by the authority service with label ``operator_configured_machine``;
4. ``ledger.gate(store, 'checkin1->execute') == []``;
5. one worker step of the approved plan reaches preflight and passes the real inventory probe;
6. its ledger rows are recorded (no refused or unmaterialised step entry anywhere in the run);
7. the run ends with an honest receipt from the sole sink (``QUALIFIED ENDING`` or ``DIAGNOSTIC DELIVERY``
   present, ``NOT GOVERNED`` absent, nothing accepted that is not).

The approval's decision justification is the run's own review evidence, and the derive step completes:
its blind verifier never sees the producer's result, derives its own value from the step's inputs, and
the controller compares the two within the tolerance the plan approved. A second case drives the same
run from a request whose plan holds an R2 decide step: its RDJ case is a governed seat, credited only
from its observed session, and the approval names it.

Beyond milestone 7, every case goes on: every plan step closes (8); kill-the-result, the fresh CI3 triad and each
seat the review policy owes run and discharge their rows (9); CHECK-IN 3 is resolved by renewed attested operator
authority on its exact final-task action (10); the CHECK-IN 3 gate passes, deciding the final task with the RDJ case
on that action, every review point's credited controller seat and the accepted output that answers the request (11);
and the run delivers through the sink, whose receipt does not accept it while anything withholds acceptance (12).

The inert worker reports the input it consumed (its whole prompt, in the estimator RAVEL sizes a packet with) and no
account usage, so the engagement envelope stays unknown and the delivery is never accepted.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import sys

import pytest

from ravel.controller import entry, graph, ledger, testing
from ravel.controller.ledger import state as ledger_state

REQUEST = (b"Estimate the yield of a fictional widget process in a toy model and report the value "
           b"with its uncertainty.")
# The same request with a consequential choice: the inert planner adds an R2 decide step, whose RDJ case the
# controller dispatches as an observed seat before CHECK-IN 1.
METHOD_CHOICE = "Choose the derivation method first."
REQUEST_R2 = REQUEST + b" " + METHOD_CHOICE.encode()
# The identity of an installed, read-only RAVEL (a test process runs from a checkout).
INSTALLED = {"kind": "installed", "package_dir": "/read-only/site-packages/ravel", "version": "0", "checkout": None,
             "writable_by_controller_user": False, "symlinks": [], "selectors": {}, "digest": "tree:" + "0" * 64}
TRANSPORT = "claude-cli-worker"
MODEL = "claude-fixture-model"
FLAGS = ("-p", "--output-format", "--model", "--effort", "--json-schema", "--setting-sources", "--restricted",
         "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--tools", "--allowedTools",
         "--max-budget-usd", "--mcp-config")
MACHINE_CHECKINS = ("approve_plan", "go", "deviation", "final")
SERVICES = ("ledger", "authority", "sink", "instructions", "judgment", "confine")

# The inert worker: the restricted CLI worker transport's executable. It reads the RAVEL-built packet,
# starts the broker MCP server its configuration names, writes the step's declared outputs through the
# broker (the frame and the plan from the controller's own inputs; a derivation first reads its governed
# inputs through the broker and names them as its result's provenance) and prints the CLI envelope whose
# structured output is the final record. Standard library only (it runs inside the worker sandbox).
WORKER = r'''
import hashlib, json, os, re, subprocess, sys, uuid
from pathlib import Path

METHOD_CHOICE = "Choose the derivation method first."
LEDGER, YIELDS = "outputs/normalization-ledger.json", "outputs/yields.json"
# The toy model's own normalization: every factor from the generated weights to the delivered yield (2 pb x 1 pb^-1 x
# 50/100 of the generated weight selected = 1 event), so the normalization check has a real subject to recompute.
TOY_LEDGER = {"schema_version": 1, "sample": "fictional widget process (toy model)",
              "luminosity": {"value": 1.0, "unit": "pb^-1", "source": "the toy model stated in the request"},
              "sigma": {"value": 2.0, "unit": "pb", "order": "LO", "tool": "toy model", "pdf": "none (toy model)",
                        "scales": "none (toy model)", "process_basis": "fictional widget process",
                        "source": "the toy model stated in the request"},
              "generated": {"sumw": 100.0, "sumw2": 100.0},
              "selected": {"toy-region": {"sumw": [50.0], "sumw2": [25.0]}}, "bin_convention": "per-bin"}

def between(text, start, end):
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    return text[i:j if j >= 0 else len(text)]

def resolve(schema, root):
    while isinstance(schema, dict) and str(schema.get("$ref", "")).startswith("#/"):
        node = root
        for token in schema["$ref"][2:].split("/"):
            node = node.get(token, {}) if isinstance(node, dict) else {}
        schema = node
    return schema if isinstance(schema, dict) else {}

def instance(schema, root, depth=0):
    schema = resolve(schema, root)
    if depth > 12:
        return None
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            options = [resolve(o, root) for o in schema[key]]
            return instance(next((o for o in options if o.get("type") == "null"), options[0]), root, depth + 1)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = "null" if "null" in kind else kind[0]
    if kind == "object" or (kind is None and "properties" in schema):
        props = schema.get("properties") or {}
        return {n: instance(props.get(n, {}), root, depth + 1) for n in schema.get("required") or ()}
    if kind == "array":
        return [instance(schema.get("items") or {}, root, depth + 1) for _ in range(schema.get("minItems") or 0)]
    if kind == "string":
        return "fictional inert value"
    if kind in ("integer", "number"):
        return max(schema.get("minimum") or 0, 0)
    if kind == "boolean":
        return False
    return None

def documents(workspace):
    found = []
    base = Path(workspace) / "inputs"
    for path in sorted(base.rglob("*.json")) if base.is_dir() else ():
        try:
            found.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass
    return found

def search(value, key):
    if isinstance(value, dict):
        if isinstance(value.get(key), str):
            return value[key]
        for child in value.values():
            hit = search(child, key)
            if hit:
                return hit
    if isinstance(value, list):
        for child in value:
            hit = search(child, key)
            if hit:
                return hit
    return None

def frame(docs):
    reading = next((d for d in docs if isinstance(d, dict) and isinstance(d.get("deliverables"), list)
                    and d.get("kind") != "question-frame"), {})
    request = next((s for d in docs for s in [search(d, "request_sha256")] if s), "0" * 64)
    rows = [{"id": re.sub(r"[^A-Za-z0-9_-]", "-", r["id"])[:64], "reading_ref": r["id"],
             "description": str(r.get("description") or r.get("quantity") or r["id"]),
             "acceptance": "the value with its uncertainty", "statistic": None, "units": None}
            for r in reading.get("deliverables") or () if isinstance(r, dict) and isinstance(r.get("id"), str)]
    return {"schema_version": 1, "kind": "question-frame", "request_sha256": request,
            "objective": "Report the fictional quantity with its uncertainty.", "deliverables": rows,
            "constraints": [], "unknowns": [],
            "assumptions": [{"number": 1, "statement": "The toy model is exact.", "basis": "stated in the request",
                             "physics_critical": False}], "boundaries": []}

def plan(docs, step):
    context = next(d for d in docs if isinstance(d, dict) and d.get("schema") == "judgment-plan.v1")
    output = "outputs/result.json"
    derive = {"id": "derive-value", "kind": "derive", "purpose": "Derive the fictional quantity.",
              "inputs": [{"artifact": "reading"}],
              "outputs": [{"path": output, "kind": "result", "required": True},
                          {"path": LEDGER, "kind": "normalization-ledger", "required": True},
                          {"path": YIELDS, "kind": "binned-values", "required": True}], "depends_on": [],
              "budget_share": {"fraction": 0.5}, "protocols": [], "review": [], "obligations": [],
              # A blind verifier's own value is compared with the derived one within this approved tolerance.
              "verification": {"output": output, "pointer": "/value", "unit": "1", "relative_tolerance": 0.05},
              # The prediction's normalization audit recomputes the delivered yields from the step's own ledger.
              "check_inputs": {"check:physics.normalization_ledger.check": {"ledger": {"output": LEDGER},
                                                                            "delivered": {"output": YIELDS}}}}
    # The derived value is certified against the task contract, which the derivation never reads: the input
    # closure of its result (the fit) must not contain that reference.
    contract = next(({"path": r["artifact"], "sha256": r["sha256"]} for r in step.get("inputs") or ()
                     if isinstance(r, dict) and "/contract-" in str(r.get("artifact"))), None)
    if contract is not None:
        derive["check_inputs"]["check:validation.input_closure.check"] = {"fit": {"output": output},
                                                                          "reference": contract}
    steps = [derive]
    if any(METHOD_CHOICE in str(d.get("request")) for d in docs if isinstance(d, dict)):
        steps.insert(0, {"id": "choose-method", "kind": "decide", "purpose": "Choose how to derive the fictional quantity.",
                         "question": "Which derivation method should the run use?",
                         "action": {"summary": "Choose the derivation method for the fictional quantity.",
                                    "kind": "method_choice"},
                         "declared_class": "R2", "inputs": [{"artifact": "reading"}],
                         "outputs": [{"path": "outputs/judgment-record.json", "kind": "judgment-record",
                                      "required": True}], "depends_on": [], "budget_share": {"fraction": 0.1},
                         "protocols": [], "review": [], "obligations": []})
    return {"schema_version": 1, "kind": "judgment-plan", "frame_sha256": context["frame_sha256"],
            "rationale": "One derivation of the fictional quantity.", "steps": steps,
            "deliverables": [{"id": d["id"], "status": "planned", "outputs": [{"step": "derive-value", "path": output}]}
                             for d in context["frame"]["deliverables"]]}

def attacks(step):
    subject = ((step.get("parameters") or {}).get("judgment") or {}).get("subject") or {}
    rows = [{"axis": n, "attack": f"The {n} could be wrong.", "test": f"Recheck the {n}.", "outcome": "survives",
             "evidence": ["inputs/controller-plan.json"]} for n in ("basis", "acceptance", "statistics")]
    return {"schema_version": 1, "kind": "judgment-attacks",
            "subject": {"plan_sha256": subject.get("plan_sha256", "0" * 64),
                        "draft_sha256": subject.get("draft_sha256", "0" * 64)}, "attacks": rows}

def decision(step):
    # The decide step's judgment record: two options, the cheaper one chosen, no default adopted.
    judgment = (step.get("parameters") or {}).get("judgment") or {}
    return {"schema_version": 1, "kind": "judgment-record", "id": "judgment-" + step["id"], "step": step["id"],
            "question": "Which derivation method should the run use?",
            "options": [{"id": "direct", "description": "Derive the quantity directly from the toy model.",
                         "predicted_consequences": "The exact toy value."},
                        {"id": "sampled", "description": "Estimate the quantity by sampling the toy model.",
                         "predicted_consequences": "The same value with sampling noise, at a higher cost."}],
            "chosen": "direct", "rationale": "The toy model is exact, so the direct derivation is the cheaper sufficient one.",
            "action": dict(judgment.get("action") or {"summary": "Choose the derivation method."}),
            "triggers": [], "protocol_evidence": {},
            "reversibility": {"kind": "reversible", "note": "The method can be changed before the derivation runs."},
            "budget_impact": {"note": "The choice itself spends nothing."}}

def content(path, step, docs, consumed):
    if "/assumption-audit-" in path:
        subject = next(d for d in docs if isinstance(d, dict) and d.get("kind") == "delivery-assumption-subject")
        # The stated exact-model premise has low severity in this fictional control.
        return {"audit": {"schema_version": 1, "kind": "assumption-audit", "items": [
            {"id": a["id"], "statement": a["statement"], "severity": 1, "controlled": False,
             "locators": [a["locator"]]} for a in subject["assumptions"]]},
            "result": {"assumptions_reported": subject["reported"]}}
    if path.endswith("question-frame.json"):
        return frame(docs)
    if path.endswith("judgment-plan.json"):
        return plan(docs, step)
    if path.endswith("judgment-attacks.json"):
        return attacks(step)
    if path.endswith("judgment-record.json"):
        return decision(step)
    if path.endswith("review.json"):
        return {"schema_version": 1, "kind": "inert-review", "verdict": "accept", "findings": []}
    if path.endswith(LEDGER):
        return TOY_LEDGER
    if path.endswith(YIELDS):
        return {"toy-region": [1.0]}
    if "/independent-" in path:
        # A blind verifier's own value of the quantity, derived from its inputs (the toy model gives the same).
        return {"schema_version": 1, "kind": "inert-independent-value", "value": 1.0, "uncertainty": 0.1}
    result = {"schema_version": 1, "kind": "inert-result", "value": 1.0, "uncertainty": 0.1}
    if step.get("kind") == "derive":
        result["inputs"] = consumed  # the provenance of the derived value: the governed inputs it read
    return result

def governed(workspace, step):
    """The workspace copies of the step's governed inputs and the run pins they carry; read through the broker."""
    pins = {}
    for row in step.get("inputs") or ():
        artifact, sha = row.get("artifact"), row.get("sha256")
        if isinstance(artifact, str) and isinstance(sha, str):
            path = "steps/" + artifact.replace(":", "/", 1) if ":" in artifact else artifact
            pins[(artifact.rsplit(":", 1)[-1].rsplit("/", 1)[-1], sha)] = {"path": path, "sha256": sha}
    reads, consumed = [], []
    base = Path(workspace) / "inputs" / "artifacts"
    for copy in sorted(base.glob("*/*")) if base.is_dir() else ():
        pin = pins.get((copy.name, hashlib.sha256(copy.read_bytes()).hexdigest()))
        if pin is not None:
            reads.append(copy.relative_to(workspace).as_posix())
            consumed.append(pin)
    return reads, consumed

def broker(argv, workspace, calls):
    """One session with the broker MCP server the configuration names; ``calls(tool names)`` gives the tool calls."""
    entry = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())["mcpServers"]["ravel"]
    server = subprocess.Popen([entry["command"], *entry["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True)
    replies = []

    def send(method, params):
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": len(replies) + 1, "method": method,
                                       "params": params}) + "\n")
        server.stdin.flush()
        replies.append(json.loads(server.stdout.readline()))
        return replies[-1]

    send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "inert-worker"}})
    names = [t["name"] for t in send("tools/list", {})["result"]["tools"]]
    for name, arguments in calls(names):
        send("tools/call", {"name": name, "arguments": arguments})
    server.stdin.close()
    server.wait()
    (workspace / "scratch").mkdir(exist_ok=True)
    (workspace / "scratch" / "broker-replies.json").write_text(json.dumps(replies))
    return replies


def envelope(argv, record, prompt=""):
    # The usage it reports is what it consumed: the whole prompt it read, in the estimator RAVEL sizes a packet with
    # (four bytes a token), so a session that read its packet never reports less input than the packet held. The
    # provider reports that input split into uncached input, cache writes and cache reads, as the real result does.
    model = argv[argv.index("--model") + 1] if "--model" in argv else "claude-fixture-model"
    consumed = max(1, (len(prompt.encode()) + 3) // 4)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                      "session_id": str(uuid.uuid4()), "num_turns": 2, "total_cost_usd": 0.001,
                      "usage": {"input_tokens": consumed // 3, "cache_creation_input_tokens": consumed // 3,
                                "cache_read_input_tokens": consumed - 2 * (consumed // 3), "output_tokens": 40},
                      "modelUsage": {model: {"outputTokens": 40}}, "structured_output": record}))
    return 0


def conformance(argv, workspace, prompt=""):
    """The transport qualifier's conformance task: read the nonce, write it back, list the served tools, finish."""
    nonce = json.loads((workspace / "inputs" / "conformance.json").read_text())["nonce"]
    broker(argv, workspace, lambda names: [("ws_read", {"path": "inputs/conformance.json"}),
                                           ("ws_write", {"path": "outputs/conformance.txt", "content": nonce}),
                                           ("ws_write", {"path": "outputs/surface.txt", "content": "\n".join(names)})])
    return envelope(argv, {"completed": True, "summary": "The conformance input was read and its nonce written."},
                    prompt)


def main(argv):
    here = Path(__file__).resolve().parent
    if argv == ["--version"]:
        print("fake-cli 9.9.9")
        return 0
    if "--help" in argv:
        sys.stdout.write((here / "help.txt").read_text())
        return 0
    if argv == ["auth", "status", "--json"]:  # the login preflight's prompt-free status observation
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        return 0
    prompt = sys.stdin.read()
    workspace = Path(os.getcwd())
    if "inputs/conformance.json" in prompt:
        return conformance(argv, workspace, prompt)
    manifest = re.search(r"manifest sha256: ([0-9a-f]{64})", prompt)
    # A duty heading prints its unit digest or, in the compact packet, its manifest index.
    duties = re.findall(r"^--- \[duty\] (\S+) (?:sha256:[0-9a-f]{64}|index:[0-9]+)$",
                        between(prompt, "== Duty units", "\n== Context units") or "", re.M)
    try:
        step = json.loads(between(prompt, "== Step specification (step.v1) ==\n", "\n\n== ") or "{}")
    except ValueError:
        step = {}
    schema = {}
    block = between(prompt, "== Output contract ==\n", "\n\n== ")
    if block:
        try:
            schema = json.loads(block.partition("\n")[2])
        except ValueError:
            schema = {}
    docs = documents(workspace)
    reads, consumed = governed(workspace, step) if step.get("kind") == "derive" else ([], [])
    writes = [(row["path"], json.dumps(content(row["path"], step, docs, consumed), indent=1, sort_keys=True))
              for row in step.get("outputs") or () if isinstance(row, dict) and isinstance(row.get("path"), str)]
    broker(argv, workspace, lambda names: [("ws_read", {"path": p}) for p in reads]
           + [("ws_write", {"path": p, "content": c}) for p, c in writes])
    record = instance(schema, schema) if schema else {}
    record = record if isinstance(record, dict) else {}
    evidence = "final_record#/kind"
    record["instruction_ack"] = {**(record.get("instruction_ack") or {}),
                                 "manifest_sha256": manifest.group(1) if manifest else None}
    record["checklist"] = [{"unit": u, "status": "done", "evidence": evidence, "note": None} for u in duties]
    parameters = step.get("parameters") or {}
    items = [r["id"] for r in list(parameters.get("reviewer_items") or ()) + list(parameters.get("must_check") or ())
             + list((parameters.get("judgment") or {}).get("must_check") or ())
             if isinstance(r, dict) and isinstance(r.get("id"), str)]
    if items or "item_verdicts" in (schema.get("properties") or {}):
        record["item_verdicts"] = [{"item": i, "verdict": "pass", "evidence": [evidence], "note": None}
                                   for i in dict.fromkeys(items)]
    return envelope(argv, record, prompt)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def _operator(*argv):
    """``ravel operator <argv>`` from the operator's own channel; returns (status, output)."""
    from ravel.controller.authority import cli
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = cli.main(list(argv))
    return status, out.getvalue() + err.getvalue()


def _install_worker(root, monkeypatch):
    """The inert executable as the CLI worker transport, probed for real; returns the agent preferences.

    No qualification record is written here: the operator qualifies the transport into the run's
    store once the run exists (``_qualify``).
    """
    from ravel.workflow import transport_registry as tr
    bin_dir = root / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("RAVEL_TEST_TRUSTED_BIN", str(bin_dir))
    (root / "claude-login").chmod(0o700)  # login state is owner-private
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root / "claude-login"))
    # The owner's own setup step places the file-backed worker login beside each worker workspace.
    from test_p04_support import owner_login_files
    owner_login_files(monkeypatch)
    (bin_dir / "help.txt").write_text("Usage\n" + "\n".join(f"  {flag} <x>" for flag in FLAGS) + "\n")
    executable = bin_dir / "claude"
    executable.write_text(f"#!{sys.executable} -B\n" + WORKER)
    executable.chmod(0o755)
    probe = tr.probe(TRANSPORT, executable=str(executable))
    assert not probe["unusable"], probe
    assert Path(tr.qualification_path(TRANSPORT)).is_relative_to(root)
    _catalogue_overlay(root, monkeypatch, MODEL)
    return {"schema_version": 1, "kind": "agent-preferences", "families": {},
            "transport_preference": [TRANSPORT], "tier_models": {tier: {TRANSPORT: MODEL} for tier in tr.TIERS}}


def _catalogue_overlay(root, monkeypatch, model):
    """The fixture model as a catalogue overlay row: the operator channel refuses an uncatalogued model."""
    from ravel.workflow import model_catalogue, transport_registry as tr
    # The fictional model declares the input window of its stated family and class (its packet budget).
    path = model_catalogue.adopt(model, family="anthropic", class_="strong", tiers=list(tr.TIERS),
                                 context_tokens=1_000_000, max_output_tokens=128_000,
                                 path=root / "models-catalogue.json")
    # The inert CLI's --effort flag accepts these levels; declare that fictional model
    # capability explicitly now that selection checks the catalogue as well as CLI flags.
    catalogue = json.loads(path.read_text())
    next(row for row in catalogue["models"] if row["id"] == model)["efforts"] = ["low", "medium", "high", "max"]
    model_catalogue.validate(catalogue)
    path.write_text(json.dumps(catalogue, indent=2, sort_keys=True) + "\n")
    monkeypatch.setenv(model_catalogue.OVERLAY_ENV, str(path))


@pytest.fixture
def run(tmp_path, monkeypatch):
    """One inert autonomous run, configured by the operator and driven unattended to its end."""
    yield from _drive(tmp_path, monkeypatch, REQUEST)


@pytest.fixture
def run_r2(tmp_path, monkeypatch):
    """The same run from the request whose plan holds an R2 decide step (its RDJ case is a governed seat)."""
    yield from _drive(tmp_path, monkeypatch, REQUEST_R2)


@pytest.fixture
def run_r3_approval(tmp_path, monkeypatch):
    """A receipted high-consequence cost raises the approval itself above R2."""
    yield from _drive(tmp_path, monkeypatch, REQUEST, r3_approval=True)


def _drive(tmp_path, monkeypatch, request, *, r3_approval=False):
    from ravel.workflow import sandbox
    if sandbox.available() is None:
        pytest.fail("the wave-A gate needs the OS worker sandbox; this host offers none")
    root = Path(os.path.realpath(tmp_path))
    for name in ("state", "home", "claude-login", "bin", "operator"):
        (root / name).mkdir()
    monkeypatch.setenv("RAVEL_STATE_DIR", str(root / "state"))
    monkeypatch.setenv("HOME", str(root / "home"))
    for name in ("RAVEL_WORK_ROOT", "RAVEL_TRANSPORT_PATH", "RAVEL_AGENT_TRIPWIRE", "RAVEL_OPERATING_MODE",
                 "RAVEL_RESTRICTED_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])  # a controller declaration lasts for its process
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:  # the operator's own terminal is not an agent session
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    confine = importlib.import_module("ravel.controller.confine")
    identity = importlib.import_module("ravel.controller.confine.identity")
    for holder in (identity, confine):
        monkeypatch.setattr(holder, "code_identity", lambda **_: dict(INSTALLED))
    sources = root / "operator" / "restricted-sources.json"
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    preferences = _install_worker(root, monkeypatch)
    status, output = _operator("init", "--mode", "autonomous", "--store-root", str(root / "store"),
                               "--machine-checkins", ",".join(MACHINE_CHECKINS),
                               "--wait-bound", "3600",
                               "--allow-unconfined", "false", "--restricted-sources", str(sources),
                               "--agent-preferences", json.dumps(preferences))
    assert status == 0, output
    store = entry.start(request, channel="operator-file", rundir=root / "runs" / "r1", unattended=True,
                        origin={"entry": "drive", "source": "request-file", "channel": "operator-file"})
    if r3_approval:
        # Operator-supplied before intake's run_init snapshot: current verified bytes, no classifier seam.
        (store.run_dir / "inputs").mkdir()
        (store.run_dir / "inputs" / "cost_preflight.json").write_text(json.dumps({
            "mode": "calculation", "points": 50, "walltime_h": [0.1, 0.2]}))
    _qualify(root, store)
    try:
        with testing.seams(False, controller=True):  # a production process: every in-process seam is refused
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                observation = entry.drive(store, unattended=False,
                                          sleep=lambda seconds: None, poll_seconds=0)
            if r3_approval:
                from ravel.controller.authority import current
                assert current(store, "approve_plan") is None, "R3 must wait for attested authority"
                assert entry._pending(observation), _pending_diagnostic(store, observation, err.getvalue())
                [pending] = entry._pending(observation)
                assert pending["payload"]["authority_kind"] == "approve_plan", (observation, err.getvalue())
                request_id = pending["payload"]["pending"]["request"]
                code = re.findall(r"--code (\S+)", err.getvalue())[-1]
                status, output = _operator("answer", "--run", store.run_id, "--request", request_id,
                                           "--code", code, "--decision", "approve")
                assert status == 0, output
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    observation = entry.drive(store, unattended=False, resume=True,
                                              sleep=lambda seconds: None, poll_seconds=0)
            # final_task is R3 even when plan approval is R2. The real authority
            # waits for a new authenticated answer on the final view, never reuses CI1.
            assert entry._pending(observation), _pending_diagnostic(store, observation, err.getvalue())
            [pending] = entry._pending(observation)
            assert pending["payload"]["authority_kind"] == "final", (observation, err.getvalue())
            request_id = pending["payload"]["pending"]["request"]
            code = re.findall(r"--code (\S+)", err.getvalue())[-1]
            status, output = _operator("answer", "--run", store.run_id, "--request", request_id,
                                       "--code", code, "--decision", "accept")
            assert status == 0, output
            observation = entry.drive(store, unattended=True, resume=True,
                                      sleep=lambda seconds: None, poll_seconds=0)
        yield store, entry.summary(store, observation)
    finally:
        ledger_state.forget(store)


def _qualify(root, store):
    """The operator's live qualification of the inert transport, retained in the run's store (SW09).

    The real qualifier runs its conformance task through the CLI adapter in the sandbox, in a separate
    empty run directory, and records the passed observation in the controller run's store.
    """
    from ravel.workflow import transport_registry as tr
    from ravel.workflow.transports import cli_worker
    record = cli_worker.qualify(TRANSPORT, rundir=root / "qualification", model=MODEL,
                                controller_rundir=root / "runs" / "r1")
    assert record["status"] == "live_qualified" and all(row["passed"] for row in record["steps"]), record
    assert list(tr.store_qualifications(store).values()) == [record]


def _records(store, kind):
    return [row["record"] for row in store.scan(kind)]


def _unmet(store, transition):
    return sorted(row.get("id") or row.get("entry") for row in ledger.gate(store, transition))


def _pending_diagnostic(store, observation, stderr):
    failed = []
    for row in store.scan("step-validation"):
        record = row["record"]
        report = record.get("report") or {}
        if report.get("passed") is False:
            failed.append({"record": row["id"], "step": record.get("step_id"), "seat": record.get("seat"),
                "results": [{key: str(item.get(key))[:1600] for key in ("check_id", "status", "reason", "diagnostics")}
                            for item in report.get("results") or [] if item.get("status") != "passed"]})
    from ravel.workflow import agent_worker, broker as worker_broker
    worker_failures = []
    for entry in worker_broker.ledger(store.run_dir, "worker-receipts"):
        receipt = json.loads(worker_broker.locate(store.run_dir, entry["record"]["pin"]["path"]).read_text())
        if receipt.get("status") == "ok":
            continue
        ws = agent_worker.workspace(store.run_dir, receipt["node_id"], receipt["attempt"])
        tools = ws / "scratch/tools.json"
        worker_failures.append({"role": receipt["role"]["id"], "status": receipt["status"],
            "failure": receipt.get("failure"), "outcome": receipt.get("outcome"),
            "credited_outputs": receipt.get("credited_outputs"), "broker": receipt.get("broker"),
            "served_tools": json.loads(tools.read_text()) if tools.is_file() else None})
    return json.dumps({"observation": observation, "where": _where(store),
                       "failed_validators": failed, "worker_failures": worker_failures, "stderr": stderr}, default=str)


def _where(store):
    """Where the run stopped, for a failing milestone: judgment events, refusals, held outcomes, the ending."""
    rows = [{"event": r.get("event"), "status": r.get("status"), "problems": r.get("problems"),
             "verdict": r.get("verdict"), "credited": r.get("credited")} for r in _records(store, "judgment-event")]
    held = [{"step": r.get("step_id"), "status": r.get("status"), "reason": r.get("reason")}
            for r in _records(store, "step-outcome") if r.get("status") != "completed"]
    refusals = [{"step": r.get("step_id"), "reason": r.get("reason"), "detail": str(r.get("detail"))[:300]}
                for r in _records(store, "step-refusal")]
    ending = [{"reason": r.get("reason"), "code": r.get("code")} for r in _records(store, "qualified-ending")]
    return json.dumps({"judgment": rows, "held": held, "refusals": refusals, "ending": ending}, default=str)[:4000]


def _plan_steps(store):
    """Step ids of the approved controller plan (not the judgment planning seats)."""
    found = set()
    for row in _records(store, "plan"):
        if row.get("source") == "judgment-planning" or not row.get("blob"):
            continue
        plan = json.loads(store.get_blob(row["blob"]))
        for step in (plan or {}).get("steps") or ():
            found.add(step["id"])
    return found


def _installed_plan(store):
    """The controller plan the run installed last (a planning seat's candidate has no revision number)."""
    rows = [r for r in _records(store, "plan") if type(r.get("revision")) is int and r.get("blob")]
    return json.loads(store.get_blob(rows[-1]["blob"]))


def _assert_milestones(store, summary, *, authority_label="operator_configured_machine"):
    """The gate's seven milestones on one driven run; returns the approval decision's rdj evidence."""
    # 1. Intake: every intake row is discharged from its enforcing action's record.
    assert _unmet(store, "intake->route_select") == [], _where(store)
    # 2. The plan and its review discharge every row the CHECK-IN 1 transition requires.
    assert _unmet(store, "plan_review->checkin1") == [], _where(store)
    # 3. CHECK-IN 1 is resolved by the authority service under the operator's configuration.
    approvals = [r for r in _records(store, "authority") if r.get("kind") == "approve_plan"]
    assert approvals, ("CHECK-IN 1 was never resolved", _where(store))
    assert approvals[-1].get("label") == authority_label, approvals[-1]
    assert approvals[-1].get("decision") == "approve", approvals[-1]
    # 4. The execute transition holds no unmet row.
    assert _unmet(store, "checkin1->execute") == [], _where(store)
    # The approval decision's decision justification is the run's own review evidence: its GATE row names the
    # credited CHECK-IN 1 review of the approved plan, read from an observed blind seat session.
    decided = [i for i in ledger_state.load(store, full=True).instances.values()
               if i.id == "GATE-approve_plan" and i.status == "satisfied"]
    assert decided, ("the approval decision was never discharged", _where(store))
    mapping = (decided[-1].evidence.get("providers") or {}).get("rdj") or {}
    assert mapping.get("mechanism") == "rdj_approval.mapping" and mapping.get("reviews"), decided[-1].evidence
    assert all(r["verdict"] == "accept" and r["profile"] in ("blind", "spec-denied") for r in mapping["reviews"]), mapping
    # 5. A worker step of the approved plan passed preflight and the real inventory probe.
    steps = _plan_steps(store)
    assert steps, ("no approved controller plan was bound", _where(store))
    probed = [r for r in _records(store, "step-observation")
              if r.get("step_id") in steps and (r.get("tool_inventory") or {}).get("equal") is True]
    assert probed, ("no approved-plan worker step passed the inventory probe", _where(store))
    assert probed[0]["tool_inventory"]["kind"] == "worker" and probed[0]["tool_inventory"]["differences"] == []
    # 6. Its ledger rows were recorded: no refused or unmaterialised step entry anywhere in the run.
    assert _records(store, "step-ledger-refused") == [], _records(store, "step-ledger-refused")
    outcomes = [r for r in _records(store, "step-outcome") if r.get("step_id") == probed[0]["step_id"]]
    ledger_rows = (outcomes[-1].get("outcome") or {}).get("ledger") or {}
    assert ledger_rows.get("recorded", 0) > 0 and ledger_rows.get("refused") == [], ledger_rows
    assert ledger_rows.get("unmaterialised") == 0, ledger_rows
    assert "step-ledger-unmaterialised" not in json.dumps([r for r in _records(store, "step-outcome")])
    # 7. The run's end is an honest receipt from the sole sink: nothing is accepted that is not, and no ungoverned
    # result is presented as governed.
    _assert_honest_receipt(store)
    return mapping


def _assert_honest_receipt(store):
    from ravel.controller import sink
    receipt = sink.receipt(store)
    labels = receipt.get("labels") or []
    assert "NOT GOVERNED" not in labels, labels
    unmet = _unmet(store, "deliver[accepted]")
    if receipt.get("accepted") is True:
        # Accepted only when no row of deliver[accepted] is unmet and every architecture predicate holds.
        assert unmet == [] and receipt.get("label") == "accepted" and receipt.get("qualified") is False, (unmet, receipt)
        assert receipt.get("architecture_complete") is True, receipt
        predicates = receipt.get("architecture_predicates") or {}
        assert predicates and all(value is True for value in predicates.values()), predicates
        assert not {"QUALIFIED ENDING", "DIAGNOSTIC DELIVERY", "USAGE UNKNOWN"} & set(labels), labels
    else:
        # While anything withholds acceptance, the sink's ending says so and accepts nothing.
        assert unmet, receipt
        assert receipt.get("label") in ("qualified", "diagnostic") and receipt.get("qualified") is True, receipt
        assert receipt.get("architecture_complete") is not True, receipt
        assert {"QUALIFIED ENDING", "DIAGNOSTIC DELIVERY"} & set(labels), labels
    # Delivery staffing and decision justification are mechanisms, independent of unknown usage.
    decisions = receipt["ledger"]["decisions"]
    for gate in ("delivery", "report_integrity"):
        assert not [e for e in decisions[gate]["errors"] if e["provider"] == "rdj"], decisions[gate]
    from ravel.workflow import spawn_rows
    [assumptions] = [r for r in spawn_rows.report(store.run_dir) if r["row"] == "K8"]
    assert assumptions["pending"] is False and assumptions["status"] == "satisfied", (
        assumptions.get("reason"), assumptions.get("evidence"), assumptions)
    assert assumptions["evidence"]["credit"] and assumptions["evidence"]["session"], assumptions
    return receipt


def _assert_derived_and_verified(store):
    """The derive step completed: its blind verifier never saw the result and its own value agreed."""
    done = [r for r in _records(store, "step-outcome") if r.get("step_id") == "derive-value"]
    assert done and done[-1].get("status") == "completed", ("the derive step did not complete", _where(store))
    verified = [r for r in _records(store, "step-verification") if r.get("step_id") == "derive-value"]
    assert verified and verified[-1]["outcome"] == "agree" and verified[-1]["comparison"]["passed"], verified
    assert verified[-1]["declared"]["relative_tolerance"] == 0.05


def _instances(store, row):
    return [i for i in ledger_state.load(store, full=True).instances.values() if i.id == row]


def _assert_final_review(store, summary):
    """Milestones 8-12: the execution closes, the final review runs and discharges its rows, CHECK-IN 3 is resolved,
    the final task is decided on its exact action, and the run delivers through the sink, honestly not accepted."""
    # 8. Every plan step closed: the final review transition holds no unmet row.
    assert _unmet(store, "execute->final_review") == [], _where(store)
    # 9. Kill-the-result preceded the CI3 triad with three valid P8 attacks (JR09, backed by the attack seat's credit);
    # each triad seat's fresh review is credited and the presentation passed the sink's Tier A tracing (D04).
    assert _unmet(store, "final_review->checkin3") == [], _where(store)
    [attacks] = _instances(store, "JR09")
    assert attacks.status == "satisfied" and attacks.evidence["credit"], attacks.evidence
    # The CHECK-IN 3 seats are the triad and every seat the review policy owes (the prediction claim's normalization
    # auditor), declared in the installed plan; each one's fresh review and the Tier A trace record its D04.
    seats = graph.checkin_seats(_installed_plan(store), "checkin3", graph.CI3_SEATS)
    assert seats == ["physics-critic", "skeptical-verifier", "physics-decider", "normalization-auditor",
                     "assumption-auditor"], seats
    traced = [i for i in _instances(store, "D04") if i.status == "satisfied"]
    assert sorted(i.scope["seat"] for i in traced) == sorted(f"seat:{r}:1" for r in seats), traced
    trace = _records(store, "presentation-trace")
    assert trace and trace[-1]["passed"] and trace[-1]["artifacts"] == ["derive-value:outputs/result.json"], trace
    # 10. CHECK-IN 3 is R3 and is resolved by a renewed attested operator answer.
    finals = [r for r in _records(store, "authority") if r.get("kind") == "final"]
    assert finals and finals[-1]["decision"] == "accept" and finals[-1]["label"] == "operator_command"
    assert [i.status for i in _instances(store, "CHECKIN-3")] == ["satisfied"]
    from ravel.controller.authority import rdj as authority_rdj
    from ravel.workflow import rdj_loop
    action = authority_rdj.final_action(finals[-1]["subject"]["pins"])
    evidence = rdj_loop.gate_evidence(store.run_dir, "final_task", action)
    assert evidence and evidence["action_case"]["role"] == "rdj-critic", evidence
    assert evidence["action_case"]["subject_sha256"] == action["digest"]
    final_id = [r["id"] for r in store.scan("authority") if r["record"].get("kind") == "final"][-1]
    assert evidence["action_case"]["authority"] == final_id
    assert evidence["action_case"]["authority_label"] == "operator_command"
    # 11. The CHECK-IN 3 gate passes: the final task is decided on its exact action. Its row names the RDJ case that
    # justified it, every review point's credited controller seat, and the accepted output that answers the request.
    [gate] = [r for r in _records(store, "gate") if r.get("gate") == "final_task"]
    assert gate["passed"] is True and gate["errors"] == [], gate
    [decided] = [i for i in _instances(store, "GATE-final_task") if i.status == "satisfied"]
    providers = decided.evidence["providers"]
    assert providers["rdj"]["mechanism"] == "rdj_final_task.mapping", providers["rdj"]
    assert providers["rdj"]["action_case"]["credit"] == evidence["action_case"]["credit"]
    points = providers["review_points"]
    assert sorted(points["points"]) == sorted(
        [f"RP4:C1:{r}" for r in seats[:3]] + ["RP5:C1"] + [f"RP11:parent:{r}" for r in seats[:3]]), points
    assert {s["step_id"] for rows in points["points"].values() for s in rows} == {"final_review"}
    [delivered] = points["delivery"]["outputs"]
    assert delivered["requirement_ids"] == ["original-request"] and delivered["deliverable"] == "D1", delivered
    assert delivered["artifact"]["path"] == "steps/derive-value/outputs/result.json" and points["delivery"]["descoped"] == []
    # 12. Delivery through the sole sink: the result is delivered, and the receipt accepts it exactly when nothing
    # withholds acceptance (no row of deliver[accepted] is unmet).
    assert summary["terminal"] is None and summary["next"] == [], summary
    record = _records(store, "receipt")[-1]
    assert record["kind"] == "delivery" and record["accepted"] is (_unmet(store, "deliver[accepted]") == []), record
    receipt = _assert_honest_receipt(store)
    # The delivered result, and the recorded-assumption appendix exactly when the run recorded assumptions:
    # every recorded premise travels with the delivered bytes (ASSUMPTIONS.md and ASSUMPTIONS.json).
    appendix = ["sink:ASSUMPTIONS.md", "sink:ASSUMPTIONS.json"] if receipt["assumptions"] else []
    assert [a["artifact"] for a in record["artifacts"]] == ["derive-value:outputs/result.json", *appendix], record
    if appendix:
        import hashlib
        delivered = Path(store.run_dir) / record["delivery_dir"]
        assert json.loads((delivered / "ASSUMPTIONS.json").read_text())["assumptions"] == receipt["assumptions"]
        for row in record["artifacts"][1:]:
            assert row["sha256"] == hashlib.sha256((delivered / row["path"]).read_bytes()).hexdigest(), row
    assert receipt["delivery"]["status"] == "delivered", receipt
    # Every executed mechanism has its own retained evidence. Labelled limitations
    # carry their labels; a missing recorder cannot hide in the diagnostic ending.
    mechanisms = {"C23", "SW04", "G02", "ROUTE-research", "SW30", "V09", "CT08", "SW10", "SW11",
                  "SW14", "SW18", "SW19", "SW31", "SW32"}
    assert mechanisms.isdisjoint(_unmet(store, "deliver[accepted]")), _unmet(store, "deliver[accepted]")
    for row in mechanisms:
        found = _instances(store, row)
        assert found and all(i.status != "pending" for i in found), (row, found)
        assert all(i.evidence.get("record") for i in found), (row, found)
        if row in ("V09", "CT08", "SW10", "SW11", "SW14", "SW18", "SW19", "SW31", "SW32"):
            assert all(i.evidence.get("label") for i in found), (row, found)
    _assert_independent_usage(store)


def _assert_independent_usage(store):
    """The deliver-stage envelope check reconciles the composed provider counter, read from the supervisor's capture
    of every session, with the controller's attributed usage: the broker floor (H5) holds and EG09 is not unmet."""
    checks = _records(store, "envelope-check")
    assert checks and checks[-1]["stage"] == "deliver", checks
    assert checks[-1]["broker"]["available"] is True, checks[-1]
    assert checks[-1]["floors"]["H5"]["status"] == "ok", checks[-1]
    assert "EG09" not in _unmet(store, "deliver[accepted]")
    assert graph.broker_counts(store)["requests"] > 0
    assert store.latest("provider-counter")["record"]["status"] == "reported"


def test_wave_a_gate(run):
    store, summary = run
    mapping = _assert_milestones(store, summary)
    assert mapping["rdj_cases"] == [], mapping   # the plan holds no R2 or R3 step
    _assert_derived_and_verified(store)
    _assert_final_review(store, summary)


def test_wave_a_gate_with_an_r2_decision(run_r2):
    """The plan's R2 decide step gets its RDJ case as a governed seat, credited only from its observed session."""
    store, summary = run_r2
    mapping = _assert_milestones(store, summary)
    [case] = mapping["rdj_cases"]
    assert case["step"] == "choose-method" and case["class"] == "R2", mapping
    assert case["role"] == "rdj-critic" and case["verdict"] == "accept" and case["profile"] == "blind", case
    credit = next(r for r in store.scan("step-credit") if r["id"] == case["credit"])["record"]
    assert credit["step_id"].startswith("judgment-rdj-choose-method-") and credit["credited"] is True, credit
    assert credit["own"]["query"]["subject_sha256"] == case["subject_sha256"], credit
    sessions = [r for r in _records(store, "review-session") if r.get("session_id") == case["session"]]
    assert len(sessions) == 1 and sessions[0]["role"] == "rdj-critic" and sessions[0]["fresh"] is True, sessions
    _assert_derived_and_verified(store)
    # The decide step's C01 and E28 are discharged by its RDJ case, whose seat was delivered the method ladder and the
    # operating protocols; its C08 is not applicable, citing its stored judgment record (it adopted no default).
    for row in ("C01", "E28"):
        [found] = _instances(store, row)
        assert found.status == "satisfied" and found.evidence["credit"] == case["credit"], found.evidence
        assert found.evidence["rdj_step"].startswith("judgment-rdj-choose-method-"), found.evidence
    [default] = _instances(store, "C08")
    assert default.status == "not_applicable" and default.evidence["reason"] == "not_applicable:no_default_adopted"
    assert [r["step"] for r in _records(store, "judgment-record")] == ["choose-method"]
    _assert_final_review(store, summary)


def test_wave_a_gate_with_an_approval_raised_above_r2(run_r3_approval):
    """The real P01 request dispatches observed exact-action RDJ and waits for operator authority."""
    from ravel.workflow import rdj_loop
    store, summary = run_r3_approval
    mapping = _assert_milestones(store, summary, authority_label="operator_command")
    case = mapping["action_case"]
    assert mapping["rdj_cases"] == [], mapping  # the extra case decides the action, not a plan step
    assert case["class"] == "R3" and case["subject_sha256"] == mapping["action_digest"]
    assert case["role"] == "rdj-critic" and case["verdict"] == "accept" and case["profile"] == "blind"
    assert case["authority_label"] == "operator_command"
    credits = [r for r in _records(store, "step-credit") if r.get("step_id", "").startswith("authority-rdj-")
               and (r.get("own", {}).get("query") or {}).get("subject_sha256") == mapping["action_digest"]]
    assert len(credits) == 1 and credits[0]["credited"] is True, credits
    assert credits[0]["own"]["query"]["subject_sha256"] == mapping["action_digest"]
    [material] = [json.loads(p.read_text()) for p in (store.run_dir / "inputs" / "judgment").glob("approval-action-*.json")]
    assert material["action"]["digest"] == mapping["action_digest"]
    assert material["approval_view"]["pins"] == material["action"]["view_pins"]
    assert material["approval_view"]["items"]["steps"], "the critic needs the approval material, not only its digest"
    sessions = [r for r in _records(store, "review-session") if r.get("session_id") == case["session"]]
    assert len(sessions) == 1 and sessions[0]["fresh"] is True and sessions[0]["role"] == "rdj-critic"
    action = {"kind": "controller.approve_plan", "digest": mapping["action_digest"]}
    assert rdj_loop.compute_class(store.run_dir, "approve_plan", action)[0] == "R3"
    _assert_derived_and_verified(store)
    _assert_final_review(store, summary)


def test_composed_provider_counter_reaches_accepted_delivery(run):
    """The acceptance target: with independent usage established, the delivered run is accepted only when no row of
    deliver[accepted] is pending. Fails, listing the pending rows, while any obligation lacks its enforcing record."""
    store, summary = run
    from ravel.controller import sink
    _assert_independent_usage(store)
    receipt = sink.receipt(store)
    pending = [{"id": row.id, "stage": row.stage, "scope": row.scope, "status": row.status}
               for row in ledger_state.load(store, full=True).instances.values() if row.status == "pending"]
    assert receipt.get("accepted") is True, json.dumps({
        "unmet": _unmet(store, "deliver[accepted]"), "labels": receipt.get("labels"),
        "predicates": receipt.get("architecture_predicates"), "pending": pending}, sort_keys=True, default=str)
    assert receipt.get("architecture_complete") is True, receipt


def test_positive_control_the_harness_drives_the_real_composition(run):
    """The gate's harness reaches the real joins: if this fails, the gate's verdict is about the harness.

    Holds today: the services are the installed packages, the intake gate is empty, the inert worker
    is dispatched through the real step graph on the qualified transport, and the run's end is the
    sink's honest receipt.
    """
    store, summary = run
    absent = (graph._AbsentLedger, graph._AbsentAuthority, graph._AbsentSink, graph._AbsentInstructions,
              graph._AbsentJudgment, graph._AbsentConfine)
    for name in SERVICES:
        found = graph.service(name)
        assert not isinstance(found, absent), name
        assert getattr(found, "__name__", None) == f"ravel.controller.{name}", (name, found)
    assert _unmet(store, "intake->route_select") == []
    assert store.scan("route"), "the run never selected a route"
    dispatched = _records(store, "step-dispatch")
    assert dispatched, ("no worker was dispatched", _where(store))
    assert {r["selection"]["transport_id"] for r in dispatched} == {TRANSPORT}
    assert {r["selection"]["model"] for r in dispatched} == {MODEL}
    _assert_honest_receipt(store)
