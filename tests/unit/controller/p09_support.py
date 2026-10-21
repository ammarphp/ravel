"""Shared fixtures of the P09 analysis-route tests (no tests here).

A fictional analysis of a fictional model: no benchmark, paper, analysis, experiment, facility or
person is named. Everything runs in memory or under the test's temporary directory; nothing calls a
model, a provider, the network or a native tool.

- ``Store``: an in-memory run store with the controller's record envelopes (``append``/``read``/``scan``).
- ``compile_plan``: the installed route compiler with the adapter's computed parameters when the
  controller core is installed, else a minimal local stand-in with the same expansion rules.
- ``adopt``: writes an output where the governed step adopts it and appends its custody record.
- ``evidence_set``: complete prepare-phase evidence for a fictional request.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import re
import time

ROUTE_FILE = Path(__file__).resolve().parents[3] / "src" / "ravel" / "data" / "controller" / "routes" / "analysis.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class Store:
    """In-memory run store: append-only envelopes ``{id, kind, seq, record}``."""
    _seq = itertools.count(1)

    def __init__(self, run_id="run-fixture", root=None):
        self.run_id = run_id
        self.store_root = Path(root) if root is not None else Path("/nonexistent-store")
        self.entries = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        seq = len(self.entries) + 1
        entry = {"id": f"{kind}-{seq:06d}", "kind": kind, "seq": seq, "time_ns": time.time_ns(),
                 "record": deepcopy(record)}
        self.entries.append(entry)
        return entry["id"]

    def read(self, kind, record_id):
        for entry in self.entries:
            if entry["id"] == record_id and entry["kind"] == kind:
                return deepcopy(entry)
        raise ValueError(record_id)

    def scan(self, kind):
        return [deepcopy(e) for e in self.entries if e["kind"] == kind]

    def put_blob(self, raw):
        sha = hashlib.sha256(raw).hexdigest()
        if not hasattr(self, '_blobs'):
            self._blobs = {}
        self._blobs[sha] = bytes(raw)
        return {'sha256': sha}

    def get_blob(self, pin):
        return self._blobs[pin['sha256']]

    def path(self, *parts):
        return self.store_root.joinpath(self.run_id, *parts)


def specs():
    family = json.loads(ROUTE_FILE.read_text())
    return {spec["id"]: spec for spec in family["specs"]}


# ---- a minimal compiler stand-in (used only when the controller core is not installed) --------

PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
DEFAULT = {"inputs": [], "outputs": [], "depends_on": [], "waypoint": False, "rung": None, "budget": {},
           "protocols": [], "review": [], "instruction_sources": [], "obligations": []}


def _sub(value, names):
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda m: str(names[m.group(1)]) if m.group(1) in names and
                               not isinstance(names[m.group(1)], (dict, list)) and names[m.group(1)] is not None
                               else m.group(0), value)
    if isinstance(value, list):
        return [_sub(v, names) for v in value]
    if isinstance(value, dict):
        return {k: _sub(v, names) for k, v in value.items()}
    return deepcopy(value)


def _local_compile(spec, reading, contract, params):
    steps, expansions = [], {}
    for template in spec["steps"]:
        base = {**deepcopy(DEFAULT), **{k: deepcopy(v) for k, v in template.items() if k != "foreach"}}
        if "foreach" not in template:
            steps.append(_sub(base, params))
            expansions[template["id"]] = [template["id"]]
            continue
        ids = []
        for index, item in enumerate(params[template["foreach"]]):
            key = re.sub(r"[^A-Za-z0-9_-]", "-", str(item["id"]))[:48]
            step = _sub(base, {**params, "item": key, "index": index})
            step["id"] = f"{template['id']}.{key}"
            step["parameters"] = {**step.get("parameters", {}), "item": deepcopy(item), "index": index}
            steps.append(step)
            ids.append(step["id"])
        expansions[template["id"]] = ids
    for step in steps:
        step["depends_on"] = list(dict.fromkeys(x for d in step["depends_on"] for x in expansions.get(d, [d])))
        inputs = []
        for row in step["inputs"]:
            source, sep, rest = row["artifact"].partition(":")
            if sep and source in expansions and expansions[source] != [source]:
                inputs.extend({**row, "artifact": f"{child}:{rest}"} for child in expansions[source])
            else:
                inputs.append(row)
        step["inputs"] = inputs
    deliverables = []
    for d in (reading or {}).get("deliverables") or ():
        artifact, claim = (d.get("artifact") or {}).get("kind"), d.get("claim_kind")
        row = {"id": d["id"], "status": "open", "step": None, "output": None, "reason": "unmapped",
               "claim_kind": claim, "artifact_kind": artifact}
        for rule in spec["deliverables"]:
            match = rule["match"]
            if ("artifact" in match and artifact not in match["artifact"]) or \
                    ("claim" in match and claim not in match["claim"]):
                continue
            row.update(status="mapped", step=rule["step"], output=rule["output"], reason=None)
            break
        deliverables.append(row)
    plan = {"schema_version": 1, "kind": "controller-plan", "revision": 0,
            "route": {"id": spec["id"], "version": spec["version"], "spec_sha256": digest(spec)},
            "parameters": params, "steps": steps, "deliverables": deliverables,
            "waypoints": [s["id"] for s in steps if s.get("waypoint")], "checkins": deepcopy(spec.get("checkins")),
            "obligations": list(spec.get("obligations") or []), "open_obligations": [],
            "instruction_sources": list(spec.get("instruction_sources") or []), "reading_sha256": None,
            "contract_sha256": None}
    plan["sha256"] = digest({k: v for k, v in plan.items() if k != "sha256"})
    return plan


def compile_plan(spec_id, reading, contract, **extra):
    """A compiled plan of the analysis route spec ``spec_id`` with the adapter's computed parameters."""
    from importlib import import_module
    from ravel.controller.routes import analysis
    spec = specs()[spec_id]
    computed = {**analysis.parameters(spec, reading, contract), **extra}
    try:
        compiler = import_module("ravel.controller.routes.compiler")
    except ImportError:
        compiler = None
    if compiler is None:
        bound = {"detector_mode": contract.get("detector_mode"), "stat_mode": contract.get("stat_mode"),
                 "task_mode": contract.get("task_mode"), "prescribed_statistic": None}
        return _local_compile(spec, reading, contract, {**bound, **computed})
    original = compiler.bind

    def bind(route_spec, reading_, contract_, supplied=()):
        params, missing = original(route_spec, reading_, contract_, supplied)
        params.update(computed)
        return params, missing
    compiler.bind = bind
    try:
        from ravel.controller import routes
        return routes.compile(spec, reading, contract)
    finally:
        compiler.bind = original


# ---- adopted artifacts --------------------------------------------------------------------------

def adopt(store, run_dir, step_id, path, document, *, status="accepted"):
    """Write ``document`` where the governed step adopts ``step_id``'s output and record its custody."""
    raw = (json.dumps(document, indent=1, sort_keys=True) + "\n").encode() if not isinstance(document, bytes) else document
    target = Path(run_dir) / "steps" / step_id / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    store.append("custody", {"schema_version": 1, "artifact": f"{step_id}:{path}", "step_id": step_id, "attempt": 1,
                             "path": path, "destination": f"steps/{step_id}/{path}", "sha256": sha,
                             "status": status})
    return sha


def outcome(step, status="completed", **extra):
    row = {"step_id": step["id"], "attempt": 1, "status": status,
           "outputs": [{"artifact": f"{step['id']}:{o['path']}", "path": o["path"], "sha256": None}
                       for o in step.get("outputs") or ()],
           "receipts": [f"receipt-{step['id']}"], "escalation": None, "replan": None, "budget": {},
           "judgments": [], "review": {}, "reason": None}
    row.update(extra)
    return row


def record_outcome(store, step, status="completed", **extra):
    found = outcome(step, status, **extra)
    store.append("step-outcome", {"step_id": step["id"], "attempt": 1, "status": status, "outcome": found})
    return found


# ---- a fictional request ------------------------------------------------------------------------

def reading(*, scan=False, exclusion=True, figure=True, prescribed=None, full_simulation=False, values=(100, 200)):
    facts = [{"id": "F1", "type": "identifier", "value": {"text": "record 4242", "scheme": "inspire", "id": "4242"}},
             {"id": "F2", "type": "model_term", "value": {"text": "widget pair"}}]
    if scan:
        facts.append({"id": "F3", "type": "parameter_values",
                      "value": {"text": "masses " + ", ".join(map(str, values)), "values": list(values),
                                "unit": "GeV", "variable": "m_widget"}})
    deliverables = []
    if exclusion:
        deliverables.append({"id": "D1", "artifact": {"kind": "inference", "require": {}}, "claim_kind": "exclusion"})
    if figure:
        deliverables.append({"id": "D2", "artifact": {"kind": "figure", "require": {}}, "claim_kind": "exclusion"})
    constraints = []
    if prescribed:
        constraints.append({"id": "K1", "type": "prescribed_statistic",
                            "value": {"statistic": prescribed, "construction_fixed": True}})
    boundaries = []
    if full_simulation:
        boundaries.append({"id": "B1", "class": "inaccessible_input",
                           "statement": "Full simulation of the detector is requested; the available fast response "
                                        "does not supply that fidelity."})
    return {"kind": "request-reading", "facts": facts, "deliverables": deliverables, "constraints": constraints,
            "boundaries": boundaries, "ambiguities": []}


def contract(task_mode="reproduce", **extra):
    return {"schema_version": 1, "task_mode": task_mode, "detector_mode": "simpleanalysis-delphes-native",
            "stat_mode": "best-sr-counting", "compute_plan": "scan" if task_mode == "scan" else "full", **extra}


def route_analysis(**extra):
    doc = {"summary": "We reproduce the fictional widget search limit with the preserved selection and a fast "
                      "detector response, checking a cheap cutflow first.",
           "routine": {"id": "FICTIONAL_ROUTINE_1", "ecosystem": "native"}, "model": "toy widget pair model",
           "final_state": "two jets and missing momentum", "energy": "13 TeV",
           "detector_mode": "simpleanalysis-delphes-native", "stat_mode": "best-sr-counting",
           "method": "smoke rung first, then the full rung", "hepdata_record": "4242",
           "assumptions": [{"id": "A1", "statement": "The widget decays promptly.", "reason": "the model card fixes a "
                            "short lifetime", "alternatives": ["displaced decays"], "result_sensitive": True}],
           "decisions": [], "approximations": [], "mismatches": [], "escalate": []}
    doc.update(extra)
    return doc


def trap_sweep_record():
    from ravel.workflow.trap_sweep import build
    verdicts = [{"id": f"T{i}", "hit": False, "evidence": f"checked trap T{i} against the fictional card"}
                for i in range(1, 13)]
    verdicts[7] = {"id": "T8", "hit": True, "evidence": "the selection uses an outdated efficiency",
                   "consequence": "acceptance may shift by a few percent", "flag_number": 2}
    return build({"verdicts": verdicts})


def evidence_set(*, withheld=False, empty=None):
    """Prepare-phase outputs by step id and output path (complete unless ``empty`` names a file)."""
    figure_target = {"targets": [] if withheld else [
        {"figure_id": "Figure 3", "role": "summary", "caption_snippet": "Expected and observed limits on the widget mass",
         "axes": {"x": "linear", "y": "log", "source": "read-from-published"}, "source": "paper-inspection"}]}
    waypoint = ({"withheld_waypoints": [{"kind": "cutflow-monotone", "counts": [1000, 640, 300, 41]}]}
                if withheld else {"element": "the first three cutflow rows at smoke statistics",
                                  "expectation": "within ten percent of the published rows",
                                  "why_cheap": "one smoke point of one thousand events"})
    rows = {
        "env": {"outputs/environment.json": {
            "tools": [{"name": "event generator", "status": "available", "required": True},
                      {"name": "statistics engine", "status": "available", "required": True}],
            "operations": ["acquire-published", "analysis-lifecycle", "figure-comparison", "lifecycle-routine-recast",
                           "lifecycle-scan-aggregation"]}},
        "inputs.census": {"outputs/inputs/resource_census.json": {
            "rungs": {"hepdata": {"status": "OK"}, "routines": {"status": "OK"}, "code-search": {"status": "ABSENT"}}}},
        "inputs.route": {"outputs/route_analysis.json": route_analysis()},
        "inputs.traps": {"outputs/trap_sweep.json": trap_sweep_record()},
        "inputs.figures": {"outputs/figure_target.json": figure_target,
                           "outputs/gallery.json": {"figures": [] if withheld else [
                               {"figure_id": "Figure 3", "caption": "Limits on the widget mass"},
                               {"figure_id": "Figure 4", "caption": "Signal region yields"}]},
                           "outputs/waypoint.json": waypoint},
        "inputs.cost": {"outputs/cost_preflight.json": {"mode": "full", "points": 1, "status": "uncalibrated",
                                                        "basis": "no matched pilot on this host yet",
                                                        "walltime_h": None}},
    }
    if empty:
        for step_rows in rows.values():
            for path in list(step_rows):
                if path.endswith(empty):
                    step_rows[path] = {}
    return rows


def adopt_prepare(store, run_dir, plan, *, withheld=False, empty=None, cost_mode=None, skip=()):
    """Adopt complete prepare-phase evidence for ``plan`` and record each prepare step completed."""
    rows = evidence_set(withheld=withheld, empty=empty)
    if cost_mode:
        rows["inputs.cost"]["outputs/cost_preflight.json"]["mode"] = cost_mode
        grid = (plan.get("parameters") or {}).get("grid") or {}
        rows["inputs.cost"]["outputs/cost_preflight.json"]["points"] = len(grid.get("points") or ()) or 1
    by_id = {s["id"]: s for s in plan["steps"]}
    states = {}
    for step_id, outputs in rows.items():
        if step_id in skip:
            continue
        for path, document in outputs.items():
            adopt(store, run_dir, step_id, path, document)
        record_outcome(store, by_id[step_id])
        states[step_id] = {"status": "completed", "attempts": 1, "receipts": [f"receipt-{step_id}"]}
    return states


def grant(store, kind, decision="approve", *, plan=None, **extra):
    record = {"schema": "authority-record.v1", "kind": kind, "decision": decision, "label": "operator_configured_machine",
              "run_id": store.run_id, "authorizes_effects": decision in ("approve", "go"),
              "subject": {"pins": {"plan_sha256": plan["sha256"]} if plan else {}}, **extra}
    record_id = store.append("authority", record)
    return record_id


def context(store, run_dir, plan, reading_, contract_, states=None, reviews=None):
    return {"store": store, "run_dir": str(run_dir), "plan": plan, "reading": reading_, "contract": contract_,
            "state": {"steps": states or {}, "reviews": reviews or {}}, "supplied": []}
