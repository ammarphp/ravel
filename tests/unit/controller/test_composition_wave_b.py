"""Wave-B exit gate: the installed routes select in precedence order, and one inert analysis-route run
crosses CHECK-IN 2 on the real controller composition.

The coordinator treats this file as the wave-B gate (the wave-A gate, ``test_composition_wave_a``, still
runs beside it). Two parts:

- Every installed route spec compiles over an analysis reading, and route selection follows the
  start table's precedence: for each spec, a view that its own predicate accepts selects the first
  spec in (row, order) whose predicate also accepts it, never a later one.
- One inert analysis-route run, configured through the operator's own channel and driven unattended
  with every in-process seam of the controller refused, exactly as the wave-A gate drives its
  judgment-route run (same harness, same stand-ins). The request reproduces a published figure of
  a fictional search, so intake selects the ``analysis`` route; the prepare phase runs before
  CHECK-IN 1, the smoke rung ends at the early-verification waypoint, and CHECK-IN 2's declared
  seat reviews the waypoint's exact outputs. The seat's first round asks for a revision; the
  credited ``revise`` starts one bounded correction round, the waypoint producer runs again, the
  seat accepts the new subject and the GO is resolved by the authority service; the full rung and
  the verification steps then complete, and the run reaches ``execute->final_review`` with an
  empty unmet list.

The inert worker is the wave-A gate's executable with the analysis route's documents added; every
operate step runs as a confined launch that preparation bound into the plan before CHECK-IN 1
(``route_analysis.launches``), and the launched program is the standard-library inert writer below,
supplied to the run as a declared input. No model, provider or native science runs. One more thing
a test process cannot provide is stood in at its source: the public discovery services the resource
census and the data acquisition read (``discovery_http._urlopen``, the documented replacement point)
answer from a fictional published record held in this file.

The gate's milestones, in the order the run reaches them:

1. the route selected at intake is ``analysis`` and its compiled plan is the bound controller plan;
2. ``ledger.gate(store, 'plan_review->checkin1') == []`` and CHECK-IN 1 is resolved by the authority
   service with label ``operator_configured_machine``;
3. ``ledger.gate(store, 'checkin1->execute') == []``;
4. an operate step of the approved plan ran as a materialised confined launch (no worker session);
5. CHECK-IN 2's declared seat was dispatched on the waypoint's exact outputs: its first credited
   round returned ``revise``, a correction round re-ran the waypoint producer within its bound, and
   the second round accepted the new subject;
6. the GO is resolved by the authority service with label ``operator_configured_machine`` and binds
   that accepted round; ``checkin2->execute[<waypoint>]`` holds no unmet row;
7. ``ledger.gate(store, 'execute->final_review') == []``, with no refused or unmaterialised step
   entry anywhere in the run.
"""
from __future__ import annotations

from importlib import import_module
import contextlib
import io
import json
import os
import re
from pathlib import Path
import sys
import threading
import traceback
import urllib.error

import pytest

from ravel.controller import entry, graph, ledger, routes, testing
from statistics_records import with_statistics  # noqa: E402
from ravel.controller.ledger import state as ledger_state

import test_composition_wave_a as wave_a
from composition_toy_inputs import SCRIPT as TOY_INPUTS

selection = import_module("ravel.controller.routes.select")

REQUEST = (b"Reproduce the published cross-section limit of a fictional search for a heavy scalar decaying to two "
           b"photons at 13 TeV.")


# ---- route specs: compile, and select in the start table's precedence ----------------------------------------------

def _satisfying(predicate):
    """One view (field -> value) the predicate accepts, or None. A view field it does not name stays absent."""
    if "all" in predicate:
        facts = {}
        for part in predicate["all"]:
            found = _satisfying(part)
            if found is None or any(facts.get(k, v) != v for k, v in found.items()):
                return None
            facts.update(found)
        return facts
    if "any" in predicate:
        return next((f for f in map(_satisfying, predicate["any"]) if f is not None), None)
    if "not" in predicate:
        inner = predicate["not"]
        if "field" not in inner:
            return None
        flipped = {k: v for k, v in inner.items() if k != "field"}
        (op, value), = flipped.items()
        if op == "is":
            return {inner["field"]: not value}
        if op in ("eq", "in"):
            return {inner["field"]: "a-value-the-predicate-does-not-name"}
        if op in ("contains_any", "contains_all"):
            return {inner["field"]: []}
        return None
    field = predicate["field"]
    (op, value), = ((k, v) for k, v in predicate.items() if k != "field")
    return {"eq": lambda: {field: value}, "in": lambda: {field: value[0]},
            "contains_any": lambda: {field: [value[0]]}, "contains_all": lambda: {field: sorted(value)},
            "disjoint": lambda: {field: []}, "nonempty": lambda: {field: ["x"] if value else []},
            "empty": lambda: {field: [] if value else ["x"]}, "is": lambda: {field: bool(value)}}[op]()


def _view(facts):
    """A complete selection view: every field the selector reads, neutral unless ``facts`` names it."""
    neutral = {"scalar": None, "bool": False, "list": []}
    view = {name: neutral[kind] for name, kind in selection.FIELDS.items()}
    view.update(scientific_deliverables=True, deliverable_count="1")
    view.update(facts)
    return view


def _admissible(order, view):
    """The specs, in (row, order), whose predicate accepts ``view`` and that the selector's two documented exclusions
    leave admissible (the judgment route's own open-parent row included), computed here from the specs."""
    found = []
    for spec in order:
        scientific = spec.get("admits_scientific_deliverables", True)
        if not selection.evaluate(spec["match"]["when"], view):
            continue
        if scientific is False and view["scientific_deliverables"]:
            continue  # an inspection route never takes a request with scientific deliverables
        if spec["id"] != selection.JUDGMENT and view["intake_kind"] == "inspect" and scientific:
            continue  # an inspect intake never selects a scientific route
        found.append(spec["id"])
    return found


def _first_match(order, view):
    """The oracle: the first admissible spec, else the judgment route."""
    return (_admissible(order, view) or [selection.JUDGMENT])[0]


def test_every_installed_route_spec_compiles_and_selects_in_precedence_order(monkeypatch):
    from ravel.cli import _draft_route
    contract, reading, _ = _draft_route(REQUEST.decode(), None, None)
    installed = selection.installed_specs()
    assert installed, "no route spec is installed"
    for spec in installed:
        plan = routes.compile(spec, reading, contract)
        assert routes.plan_errors(plan) == [] and routes.conformance_errors(plan, spec) == [], spec["id"]
        selection.adapter_module(spec)  # an installed spec's adapter is installed
    order = selection.ordered(installed)
    keys = [(s["match"]["row"], s["match"].get("order", 0)) for s in order]
    assert keys == sorted(keys), "route selection does not follow the start table's rows"
    # The views: one per spec that its own predicate accepts, and one per pair of specs whose two views merge into a
    # view both predicates accept (the views where the precedence, not the predicate, decides).
    own = {}
    for spec in installed:
        facts = _satisfying(spec["match"]["when"])
        assert facts is not None, f"no view satisfies route {spec['id']}'s own predicate"
        if spec.get("admits_scientific_deliverables", True) is False:
            facts.setdefault("scientific_deliverables", False)
        own[spec["id"]] = facts
    views = [(spec_id, _view(facts)) for spec_id, facts in own.items()]
    for a in installed:
        for b in installed:
            merged = {**own[a["id"]], **own[b["id"]]}
            if a["id"] < b["id"] and all(own[x["id"]].get(k, v) == v for x in (a, b) for k, v in merged.items()):
                view = _view(merged)
                if all(selection.evaluate(x["match"]["when"], view) for x in (a, b)):
                    views.append((f"{a['id']}+{b['id']}", view))
    contested = 0

    def selected(view):
        monkeypatch.setattr(selection, "view", lambda contract, reading, supplied: dict(view))
        return routes.select({}, {}, [])

    for name, view in views:
        expected = _first_match(order, view)
        decision = selected(view)
        assert decision["route"] == expected, (name, decision["evidence"])
        contested += len(_admissible(order, view)) > 1
    assert contested, "no view is accepted by two specs: the precedence was never exercised"
    # The check discriminates: a selector that evaluated the rows in reverse picks another route for a contested view.
    monkeypatch.setattr(selection, "ordered", lambda specs, _o=selection.ordered: list(reversed(_o(specs))))
    assert any(selected(view)["route"] != _first_match(order, view) for _, view in views), \
        "the precedence check cannot tell a reversed table from the start table"
    # The reading this gate's run starts from selects the analysis route through the real view.
    monkeypatch.undo()
    assert routes.select(contract, reading, [])["route"] == "analysis"


# ---- the inert analysis-route run ------------------------------------------------------------------------------------

WAYPOINT = "visualize.waypoint"
CI2_SEAT = "figure-critic"
CI2_STEP = f"waypoint_review.{CI2_SEAT}"
ROUTINE = "fictional-diphoton-routine"
DETECTOR = "particle-level"
STATISTIC = "best-sr-counting"
RECORD = "9000001"  # the fictional published record the stand-in discovery service holds

# The launched inert writer: a confined operate step's program. It writes the step's declared outputs from the
# documents bound into its own argv, each stamped with its attempt (the attempt directory it runs in) and a fresh
# execution id, and nothing else. Standard library only (it runs inside the launch sandbox, network none).
WRITER = TOY_INPUTS + r"""
import json, sys, uuid
from pathlib import Path
documents = json.loads(sys.argv[2])
attempt = int(Path.cwd().parent.name)
metadata, files = toy_inputs(sys.argv[3], sys.argv[1], attempt, next(iter(documents)))
for path, value in files.items():
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value if isinstance(value, bytes) else value.encode())
for path, document in documents.items():
    target = Path(path[len("outputs/"):] if path.startswith("outputs/") else path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(document, dict):
        document = dict(document, **metadata, attempt=attempt, execution=uuid.uuid4().hex)
        if document.get("kind") == "inert-waypoint" and attempt > 1:
            document["uncertainty"] = math.sqrt(.5 * (1 - .5) / 100)
            document["uncertainty_basis"] = "binomial standard error for 50 selected of 100 unit-weight rows"
    target.write_text(json.dumps(document, indent=1, sort_keys=True))
"""

# The analysis route's worker documents, added to the wave-A inert worker: each prepare and verification step
# writes the documents ``DOCUMENTS`` names for it (computed in the test process with the installed record builders);
# CHECK-IN 2's seat asks for a revision of a first-attempt waypoint and accepts a corrected one. The record and its
# final-record findings carry the revision (``items`` of severity A), so the governed step credits a ``revise``.
LAYER = r"""
DOCUMENTS = json.loads(%r)
CI2_STEP = %r
_wave_a_content, _wave_a_envelope = content, envelope
_verdict = {}
_toy_files = {}
_TOY_ROUTINE = 'fictional-diphoton-routine'

def _waypoint_attempts(docs):
    return [d.get("attempt") for d in docs if isinstance(d, dict) and d.get("kind") == "inert-waypoint"]

def content(path, step, docs, consumed):
    documents = DOCUMENTS.get(step.get("id")) or {}
    if path in documents:
        result = dict(documents[path])
        if path == "outputs/results.json":
            # The results deck carries the run's own recipe ledger section, which the fixture computed at this
            # dispatch with the product's ledger (written beside this executable, readable in the sandbox).
            ledger = Path(__file__).with_name("recipe_ledger.json")
            section = json.loads(ledger.read_text()) if ledger.is_file() else None
            if section is not None:
                result["recipe_ledger"] = section
        if "targets" in result or ((step.get("parameters") or {}).get("validator_exports") or {}).get(path):
            workspace = Path.cwd()
            prefix = f"agent-work/{workspace.parent.name}/{workspace.name}/outputs/"
            metadata, files = toy_inputs(_TOY_ROUTINE, step["id"], int(workspace.name), report_path=path,
                                         output_prefix=prefix)
            result.setdefault("validator_inputs", {}).update(metadata["validator_inputs"])
            if "targets" in result:
                # A real preview accompanies this proposed contract; it claims no target fulfilment.
                result.update({key: metadata[key] for key in ("figure_spec", "n_figures", "figures")})
                for figure in result["figures"]:
                    figure["filename"] = figure["pdf"]
            _toy_files.update({"outputs/" + name: (value.decode("ascii") if isinstance(value, bytes) else value)
                               for name, value in files.items() if isinstance(value, str) or name.endswith(".pdf")})
        return result
    if step.get("id") == CI2_STEP:
        waypoints = [d for d in docs if isinstance(d, dict) and d.get("kind") == "inert-waypoint"]
        current = max(waypoints, key=lambda d: d["attempt"])
        first = "uncertainty" not in current
        _verdict["revise"] = first
        manifest = next(d for d in docs if isinstance(d, dict) and d.get("kind") == "review-projection")
        subject = next(a for a in manifest["artifacts"]
                       if "visualize.waypoint" in a["source_path"] and a["source_path"].endswith("/waypoint.json"))
        finding = {"id": "uncertainty-missing", "severity": "A",
                   "location": {"path": subject["source_path"], "pointer": "/expectation", "line": None},
                   "code": "uncertainty_missing", "statement": "the waypoint expectation is stated without its uncertainty",
                   "evidence": ["pin:" + subject["source_sha256"]], "closes": [], "evidence_class": "code_check",
                   "classification": {"kind": "defect", "artifact_sha256": subject["source_sha256"],
                                      "target": "visualize.waypoint",
                                      "rework_evidence": "the 50 of 100 row fraction requires its binomial standard error"}}
        _verdict["finding"] = finding
        return {"schema_version": 1, "kind": "inert-review", "verdict": "revise" if first else "accept",
                "findings": [finding] if first else []}
    return _wave_a_content(path, step, docs, consumed)

def envelope(argv, record, *args, **kwargs):
    if _verdict.get("revise"):
        record["items"] = [_verdict["finding"]]
        for row in record.get("item_verdicts") or ():
            row["verdict"] = "fail"
    return _wave_a_envelope(argv, record, *args, **kwargs)
"""


def _launch(step_id, documents):
    """A prepared confined launch of the inert writer for one operate step (``route_analysis.launches``)."""
    return {"argv": [sys.executable, "-I", "-c", WRITER, step_id, json.dumps(documents, sort_keys=True), ROUTINE]}


def _documents(plan):
    """The inert documents of every analysis step, keyed by step id and declared output path."""
    from ravel.workflow import trap_sweep
    operations = sorted({s["operation"] for s in plan["steps"] if s.get("operation")})
    traps = trap_sweep.build({"verdicts": [{"id": t, "hit": False, "evidence": "the fictional toy model has no such "
                                            "effect"} for t in trap_sweep.TRAP_IDS]})
    recast = {"kind": "inert-recast", "samples": ["fictional-signal"], "events": 100,
              "lhe_check": {"status": "PASS"}, "cutflow": [{"cut": "all events", "events": 100},
                                                          {"cut": "two photons", "events": 50}],
              "qualification": {"routine": ROUTINE, "status": "qualified"}, "detector_mode": DETECTOR}
    waypoint = {"kind": "inert-waypoint", "summary": "the smoke cutflow of the fictional signal",
                "element": "the two-photon selection", "expectation": "half of the fictional signal passes",
                "evidence": "the smoke cutflow", "figures": []}
    limits = with_statistics({"kind": "inert-limits", "statistic": "CLs", "confidence_level": 0.95,
                              "detector_mode": DETECTOR, "headline": "the fictional signal strength limit"})
    figures = {"kind": "inert-figures", "figures": [{"id": "F1", "path": "figure.pdf", "lint": "PASS"}]}
    launches = {"recast.smoke": {"outputs/smoke/recast.json": recast},
                WAYPOINT: {"outputs/waypoint.json": waypoint},
                "run.full": {"outputs/limits.json": limits,
                             "outputs/histograms.json": {"kind": "inert-histograms", "bins": [[0, 1, 1.0]]}},
                "visualize.final": {"outputs/figures.json": figures}}
    # Expected descriptors are independent literals in the preparation source, never copied from writer metadata.
    scientific_expected = {
        "P05": {"basis": ["selected_sumw:X"], "units": "weighted_rows", "sign_convention": "signed_weight_sum",
                "covariance": [[50.0]], "population": ["X"]},
        "E07": {"pdf_member": "none finite toy enumeration",
                "generation_settings": {"kind": "finite_enumeration", "rows": 100, "selected_rows": 50}},
        "E08": {"spectrum": {}, "invisible_states": []},
        "E10": {"beam_energy": "none finite toy enumeration", "seed": "none deterministic enumeration"},
        "E13": {"weight_names": ["nominal"], "reentrant": False, "merged": False, "single_weight": True},
        "E17": {"bin_ids": ["X"]},
        "E18": {"perturbative_order": "LO", "process_basis": ["declared toy process"]},
    }
    primary_outputs = {"recast.smoke": "outputs/smoke/recast.json", WAYPOINT: "outputs/waypoint.json",
                       "run.full": "outputs/limits.json", "visualize.final": "outputs/figures.json"}
    scientific_bindings = {}
    for identifier, primary in primary_outputs.items():
        rows = list(scientific_expected) if identifier in ("recast.smoke", "run.full") else ["P05"]
        scientific_bindings[identifier] = [
            {"row": row, "expected": "inputs.route:outputs/route_analysis.json",
             "observed": identifier + ":" + primary, "validator": "descriptor-continuity",
             "expected_fields": {field: "/scientific_expected/" + row + "/" + field
                                 for field in scientific_expected[row]},
             "observed_fields": {field: "/scientific_descriptors/" + row + "/" + field
                                 for field in scientific_expected[row]}}
            for row in rows]
    route = {"kind": "inert-route-analysis", "routine": ROUTINE, "model": "a fictional heavy scalar",
             "final_state": "two photons", "energy": "13 TeV", "detector_mode": DETECTOR, "stat_mode": STATISTIC,
             "hepdata_record": RECORD, "approximations": [], "mismatches": [],
             "summary": "Reproduce the fictional record's limit figure with the preserved fictional routine.",
             "method": "particle-level smoke rung, then the full rung with signal-region counting",
             "assumptions": [{"id": "A1", "statement": "The fictional routine reproduces the published selection.",
                              "reason": "the record names this routine", "result_sensitive": True,
                              "alternatives": ["a re-implemented selection"]}],
             "scientific_expected": scientific_expected, "scientific_bindings": scientific_bindings,
             "launches": {sid: _launch(sid, docs) for sid, docs in launches.items()}}
    return {
        "env": {"outputs/environment.json": {"tools": [{"name": "python", "status": "available", "required": True,
                                                        "required_by": operations}], "operations": operations}},
        "inputs.route": {"outputs/route_analysis.json": route},
        "inputs.traps": {"outputs/trap_sweep.json": traps},
        "inputs.figures": {"outputs/figure_target.json": {"targets": [{
                               "figure_id": "F1", "axes": {"x": "linear", "y": "log"}, "source": "table 1",
                               "caption": "the limit versus the heavy scalar mass"}]},
                           "outputs/gallery.json": {"figures": [{"figure_id": "F1",
                                                                 "caption": "the limit versus the heavy scalar mass"}]},
                           "outputs/waypoint.json": {"element": "the two-photon selection",
                                                     "expectation": "half of the fictional signal passes",
                                                     "why_cheap": "the smoke rung alone"}},
        "inputs.cost": {"outputs/cost_preflight.json": {"mode": "full", "status": "uncalibrated",
                                                        "basis": "no matched pilot exists for the inert writer"}},
        "compare.reference": {"outputs/comparison.json": {
            "comparator": {"source": "table 1"}, "tolerance": "one sigma", "lattice": "the published masses",
            "basis_manifests": [{"quantity": "signal strength", "basis": "95% CLs", "unit": "1"}] * 2}},
        "verify.mechanical": {"outputs/tier_a.json": {"verdict": "PASS", "numbers": []}},
        "verify.adversary": {"outputs/tier_b.json": {"attacks": [
            {"kind": k, "attack": f"the {k} could be wrong", "tested_by": f"recheck the {k}"}
            for k in ("basis", "acceptance", "statistics")]}},
        "synthesize": {"outputs/results.json": {"headline": "the fictional limit", "numbers": []}},
    }


def _install_worker(root, monkeypatch, documents):
    """The wave-A inert executable with the analysis layer as the CLI worker transport, probed for real."""
    # The owner's own setup step places the file-backed worker login beside each worker workspace.
    from test_p04_support import owner_login_files
    owner_login_files(monkeypatch)
    from ravel.workflow import transport_registry as tr
    bin_dir = root / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("RAVEL_TEST_TRUSTED_BIN", str(bin_dir))
    (root / "claude-login").chmod(0o700)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root / "claude-login"))
    (bin_dir / "help.txt").write_text("Usage\n" + "\n".join(f"  {flag} <x>" for flag in wave_a.FLAGS) + "\n")
    # The inert transport meters the prompt it actually reads, using the packet estimator's character rule.
    # A fixed tiny count cannot represent a delivered instruction packet of this route's size.
    metered = wave_a.WORKER.replace('prompt = sys.stdin.read()',
        'prompt = sys.stdin.read()\n    globals()["_input_meter"] = -(-len(prompt) // 4)')
    metered = metered.replace('"input_tokens": 120', '"input_tokens": _input_meter')
    metered = metered.replace('    broker(argv, workspace, lambda names: [("ws_read", {"path": p}) for p in reads]',
                             '    writes.extend(_toy_files.items())\n    broker(argv, workspace, lambda names: [("ws_read", {"path": p}) for p in reads]')
    worker = metered.replace('\nif __name__ == "__main__":',
                                   TOY_INPUTS + LAYER % (json.dumps(documents, sort_keys=True), CI2_STEP)
                                   + '\nif __name__ == "__main__":')
    executable = bin_dir / "claude"
    executable.write_text(f"#!{sys.executable} -B\n" + worker)
    executable.chmod(0o755)
    probe = tr.probe(wave_a.TRANSPORT, executable=str(executable))
    assert not probe["unusable"], probe
    wave_a._catalogue_overlay(root, monkeypatch, wave_a.MODEL)
    return {"schema_version": 1, "kind": "agent-preferences", "families": {},
            "transport_preference": [wave_a.TRANSPORT],
            "tier_models": {tier: {wave_a.TRANSPORT: wave_a.MODEL} for tier in tr.TIERS}}


# The fictional world of the public discovery services: one published record with two tables, found by every search.
# Every other URL is a served 404 (a definitive absence), except forward citations and archive records (empty).
TITLE = "A fictional search for a heavy scalar decaying to two photons"
RECID, VERSION = 90000011, 1
TABLES = {
    1: {"name": "Table 1", "description": "Observed and expected upper cross-section limit versus heavy scalar mass.",
        "doi": "10.0000/fictional.9000001.t1",
        "values": [{"x": [{"value": m}], "y": [{"value": o}, {"value": e}]}
                   for m, o, e in ((200.0, 1.9, 2.1), (400.0, 0.8, 0.9), (600.0, 0.5, 0.6))]},
    2: {"name": "Table 2", "description": "Cutflow of the signal region for a reference heavy scalar signal.",
        "doi": "10.0000/fictional.9000001.t2",
        "values": [{"x": [{"value": "Two photons"}], "y": [{"value": 1000.0}]},
                   {"x": [{"value": "Mass window"}], "y": [{"value": 420.0}]}]},
}
PUBLISHED = {"recid": RECID, "version": VERSION, "title": TITLE, "resources": [],
             "record": {"recid": RECID, "version": VERSION, "title": TITLE, "resources": []},
             "data_tables": [{"id": tid, "name": t["name"], "description": t["description"], "doi": t["doi"],
                              "data": {"json": f"/record/data/{RECID}/{tid}/{VERSION}"}} for tid, t in TABLES.items()]}
EMPTY_HITS = {"hits": {"total": 0, "hits": []}}


def _published(url):
    """The fictional service's JSON document for ``url``, or None (a served 404)."""
    import re
    import urllib.parse
    parts = urllib.parse.urlsplit(url)
    query = " ".join(urllib.parse.parse_qs(parts.query).get("q", []))
    if parts.netloc == "www.hepdata.net":
        if parts.path == "/search/":
            return {"total": 1, "results": [{"inspire_id": RECORD, "recid": RECID, "title": TITLE, "arxiv_id": None,
                                             "collaborations": [], "total_tables": len(TABLES), "analyses": []}]}
        if parts.path in (f"/record/ins{RECORD}", f"/record/{RECID}"):
            return PUBLISHED
        table = re.fullmatch(rf"/record/data/{RECID}/(\d+)/{VERSION}", parts.path)
        return TABLES.get(int(table.group(1))) if table else None
    if parts.netloc == "inspirehep.net":
        if parts.path == f"/api/literature/{RECORD}":
            return {"id": RECORD, "metadata": {"control_number": int(RECORD), "external_system_identifiers": [
                {"schema": "HEPDATA", "value": f"ins{RECORD}"}]}}
        if parts.path == "/api/literature":
            return EMPTY_HITS if "refersto" in query else {"hits": {"total": 1, "hits": [{"id": RECORD, "metadata": {
                "control_number": int(RECORD), "titles": [{"title": TITLE}], "arxiv_eprints": [],
                "report_numbers": [], "collaborations": []}}]}}
    if parts.netloc == "zenodo.org" and parts.path == "/api/records":
        return EMPTY_HITS
    return None


class _Served(io.BytesIO):
    """Enough of a ``urlopen`` response for the discovery clients."""

    def __init__(self, url, body):
        super().__init__(body)
        self.url, self.status, self.headers = url, 200, {"Content-Type": "application/json"}

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def info(self):
        return self.headers


def _discovery(monkeypatch, requested):
    """The public discovery services, stood in at their documented replacement point (``discovery_http._urlopen``).

    Only the HTTPS service names in ``_published`` receive synthetic public DNS.
    Socket connections to every nonloopback INET destination fail before egress
    (a client's bulk download falls back to the served endpoint during the outage).
    Production acquisition destination checks still run; confined launches have no network.
    """
    import errno
    import ipaddress
    import socket
    from ravel.workflow import discovery_http

    def urlopen(request, timeout=None, context=None):
        url = request if isinstance(request, str) else request.full_url
        requested.append(url)
        document = _published(url)
        if document is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Served(url, json.dumps(document, sort_keys=True).encode())

    resolve = socket.getaddrinfo
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    served_hosts = {'www.hepdata.net', 'inspirehep.net', 'zenodo.org'}

    def local_only(host, *args, **kwargs):
        if host in served_hosts:
            return resolve('93.184.216.34', *args, **kwargs)
        if host not in (None, "localhost", "127.0.0.1", "::1"):
            raise socket.gaierror(socket.EAI_NONAME, f"the inert gate resolves no public name ({host})")
        return resolve(host, *args, **kwargs)

    def local_connection(sock, address, original):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            try:
                parsed = ipaddress.ip_address(host)
                parsed = getattr(parsed, 'ipv4_mapped', None) or parsed
                loopback = parsed.is_loopback
            except ValueError:
                loopback = host == 'localhost'
            if not loopback:
                raise OSError(errno.ENETUNREACH, 'the inert gate blocks nonloopback socket connections')
        return original(sock, address)

    monkeypatch.setattr(discovery_http, "_urlopen", urlopen)
    monkeypatch.setattr(socket, "getaddrinfo", local_only)
    monkeypatch.setattr(socket.socket, "connect", lambda sock, address: local_connection(sock, address, connect))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda sock, address: local_connection(sock, address, connect_ex))


class _CostOperator:
    """The inert run's operator answers its real pending cost and launch challenges through the public CLI."""

    def __init__(self, store, notifications):
        self.store, self.notifications = store, notifications
        self.answers = []

    def __call__(self, seconds):
        status, output = wave_a._operator("status", "--run", self.store.run_id)
        assert status == 0, output
        for pending in json.loads(output)["pending"]:
            if pending["kind"] != "r3_action":
                continue
            if "Uncalibrated top-rung cost" in pending["text"]:
                expected_options = {"admit", "pilot_first"}
            elif "Consequential native action" in pending["text"]:
                expected_options = {"admit", "hold"}
            else:
                continue
            assert pending["answerable"] is True
            assert {o["id"] for o in pending["options"]} == expected_options
            request = pending["request"]
            command = (rf"ravel operator answer --run {re.escape(self.store.run_id)} "
                       rf"--request {re.escape(request)} --code ([A-Z2-9-]+) --decision")
            challenge = re.search(command, self.notifications.getvalue())
            assert challenge is not None, "the real pending request did not notify its operator"
            status, answer = wave_a._operator("answer", "--run", self.store.run_id, "--request", request,
                                              "--code", challenge.group(1), "--decision", "admit")
            assert status == 0, answer
            record = json.loads(answer)
            assert record["label"] == "operator_command" and record["option"] == "admit"
            self.answers.append(record)


@contextlib.contextmanager
def _stack_samples(interval, stream):
    """Write every thread's Python stack to *stream* each *interval* seconds while the block runs.

    The long inert run needs periodic stacks to show where it is when it stalls. These are taken with the GIL
    held (``sys._current_frames``), never with ``faulthandler.dump_traceback_later``: that watchdog walks the
    other threads' frame chains and thread states without the GIL, while the controller's worker threads
    push and pop deep frame chains and its per-invocation thread pools start and retire threads. A walk
    that meets a released frame chunk or thread state kills the pytest process with SIGSEGV in the middle
    of the dump (exit 139, at a multiple of the dump interval after the drive starts). The cost of the safe
    form: a thread that holds the GIL forever also stops the samples."""
    stop = threading.Event()

    def sample():
        while not stop.wait(interval):
            names = {thread.ident: thread.name for thread in threading.enumerate()}
            lines = [f"Stack samples ({interval:g} s)\n"]
            for ident, frame in sys._current_frames().items():
                lines.append(f"Thread {ident:#x} ({names.get(ident, '?')}), most recent call last:\n")
                lines.extend(traceback.format_stack(frame))
                del frame
            stream.write("".join(lines))
            stream.flush()

    sampler = threading.Thread(target=sample, name="wave-b-stack-samples", daemon=True)
    sampler.start()
    try:
        yield
    finally:
        stop.set()
        sampler.join()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Share the single inert run between its read-only gate and harness controls."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield from _run(tmp_path_factory.mktemp("governed-run"), monkeypatch)


def _run(tmp_path, monkeypatch):
    """One inert analysis-route run, configured by the operator and driven unattended to its end."""
    from ravel.workflow import sandbox
    if sandbox.available() is None:
        pytest.fail("the wave-B gate needs the OS worker sandbox; this host offers none")
    root = Path(os.path.realpath(tmp_path))
    for name in ("state", "home", "claude-login", "bin", "operator"):
        (root / name).mkdir()
    monkeypatch.setenv("RAVEL_STATE_DIR", str(root / "state"))
    monkeypatch.setenv("HOME", str(root / "home"))
    for name in ("RAVEL_WORK_ROOT", "RAVEL_TRANSPORT_PATH", "RAVEL_AGENT_TRIPWIRE", "RAVEL_OPERATING_MODE",
                 "RAVEL_RESTRICTED_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    confine = import_module("ravel.controller.confine")
    identity = import_module("ravel.controller.confine.identity")
    for holder in (identity, confine):
        monkeypatch.setattr(holder, "code_identity", lambda **_: dict(wave_a.INSTALLED))
    _discovery(monkeypatch, [])
    from ravel.cli import _draft_route
    contract, reading, _ = _draft_route(REQUEST.decode(), None, None)
    plan = routes.compile(selection.find("analysis"), reading, contract)
    sources = root / "operator" / "restricted-sources.json"
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    preferences = _install_worker(root, monkeypatch, _documents(plan))
    # This route's declared envelope exceeds the operator's small default run.
    # Configure the inert run through the same public operator channel as its check-ins.
    bounds = graph.plan_bounds(plan)["budget"]
    status, output = wave_a._operator("init", "--mode", "autonomous", "--store-root", str(root / "store"),
                                      "--machine-checkins", ",".join(wave_a.MACHINE_CHECKINS), "--wait-bound", "60",
                                      "--allow-unconfined", "false", "--restricted-sources", str(sources),
                                      "--agent-preferences", json.dumps(preferences),
                                      "--budget", f"wall_seconds={bounds['wall_seconds']}",
                                      "--budget", f"events={bounds['events']}",
                                      "--budget", "max_redos=1", "--budget", "review_rounds=2")
    assert status == 0, output
    store = entry.start(REQUEST, channel="operator-file", rundir=root / "runs" / "r1", unattended=True,
                        origin={"entry": "drive", "source": "request-file", "channel": "operator-file"})
    # The scripted synthesizer's recipe ledger: this run's own CHECK-IN 3 section, computed by the product's ledger
    # from the run as it stands when the synthesizer is dispatched (its rows exist only once the plan does).
    from ravel.workflow import recipe_ledger
    step_graph = import_module("ravel.controller.step.graph")
    worker_packet = step_graph._worker_packet

    def packet_with_ledger(state):
        if state["acting"].get("id") == "synthesize":
            section = recipe_ledger.checkin3_section(step_graph._run_dir(state))
            (root / "bin" / "recipe_ledger.json").write_text(json.dumps(section))
        return worker_packet(state)

    monkeypatch.setattr(step_graph, "_worker_packet", packet_with_ledger)
    try:
        wave_a._qualify(root, store)
    except Exception as exc:
        print("QUALIFICATION_REFUSAL=" + json.dumps(getattr(exc, "receipt", {}), default=str))
        from ravel.workflow import agent_worker
        capture = agent_worker.capture_path(root / "qualification", "qualify.conformance", 1, "stderr")
        for path in [capture]:
            if path.is_file():
                print("QUALIFICATION_STDERR=" + path.read_text(errors="replace")[-4000:])
        raise
    try:
        with _stack_samples(120, sys.stderr):
            notifications = io.StringIO()
            cost_operator = _CostOperator(store, notifications)
            with contextlib.redirect_stderr(notifications), testing.seams(False, controller=True):
                observation = entry.drive(store, unattended=True, sleep=cost_operator, poll_seconds=0)
            if notifications.getvalue():
                print(notifications.getvalue(), file=sys.stderr)
        yield store, entry.summary(store, observation)
    finally:
        ledger_state.forget(store)


_records, _unmet = wave_a._records, wave_a._unmet


def _where(store):
    """Where the run stopped: the wave-A view, the steps that did not complete, the launch journal with each failed
    launch's stderr, and the unmet rows of the transitions this gate needs."""
    from ravel.workflow import graph_substrate
    _, _, snapshot = graph_substrate._pending(store.graph_scope(), entry.GRAPH_ID, {"run_id": store.run_id})
    print("GRAPH_FAILURES=" + json.dumps((snapshot.values or {}).get("failures"), default=str))
    print("GATE_PROVIDER_FAILURES=" + json.dumps([row["record"] for row in store.scan("gate-provider-check")
          if row["record"].get("passed") is False][-3:], default=str))
    print("NATIVE_DECISION_FAILURES=" + json.dumps([row["record"] for row in store.scan("step-fact")
          if row["record"].get("mechanism") == "native-launch-decision" and row["record"].get("passed") is False][-3:], default=str))
    from ravel.controller.routes.analysis import checkins
    plan_rows = [r for r in _records(store, "plan") if r.get("blob") and type(r.get("revision")) is int]
    if plan_rows:
        view = {"store": store, "run_dir": store.run_dir,
                "plan": json.loads(store.get_blob(plan_rows[-1]["blob"])),
                "contract": json.loads((store.run_dir / "inputs/task_contract.json").read_text()),
                "reading": json.loads((store.run_dir / "inputs/reading.json").read_text())}
        print("CHECKIN_CONTENT_ERRORS=" + json.dumps(checkins.approve_plan(view).get("errors"), default=str))
    print("ENDING_DETAILS=" + json.dumps(_records(store, "qualified-ending"), default=str))
    print("CHECKIN2_UNMET=" + json.dumps(ledger.gate(store, f"checkin2->execute[{WAYPOINT}]"), default=str))
    holes = {}
    counts = {}
    for transition in ("plan_review->checkin1", "checkin1->execute", "execute->final_review"):
        rows = ledger.gate(store, transition)
        if transition == "execute->final_review":
            print("SCOPED_UNMET=" + json.dumps([
                {k: row.get(k) for k in ("entry", "reason")} for row in rows
                if str(row.get("entry")).split("@", 1)[0] in {"I09", "E02", "E06", "E07", "E08", "E10", "P05"}],
                default=str))
        holes[transition] = [{k: row.get(k) for k in ("entry", "reason")} for row in rows][:12]
        totals = {}
        for row in rows:
            key = str(row.get("entry")).split("@", 1)[0]
            totals[key] = totals.get(key, 0) + 1
        counts[transition] = totals
    held = [{"step": r.get("step_id"), "attempt": r.get("attempt"), "status": r.get("status"),
             "reason": r.get("reason"), "detail": str(r.get("detail") or (r.get("outcome") or {}).get("detail"))[:300]}
            for r in _records(store, "step-outcome") if r.get("status") != "completed"][-6:]
    # A typed hold's evidence (the custody errors behind "an input is not a verified accepted artifact").
    print("REFUSAL_EVIDENCE=" + json.dumps([{k: r.get(k) for k in ("step_id", "attempt", "reason", "evidence")}
                                            for r in _records(store, "step-refusal")][-4:], default=str)[:6000])
    launches = _records(store, "step-launch")
    journal = [{k: r.get(k) for k in ("phase", "step_id", "attempt", "exit_status", "reason") if r.get(k) is not None}
               for r in launches][-6:]
    stderr = {}
    if launches:  # <run>/steps/<step>/attempts/<n>/outputs is a launch's only write root
        run_dir = Path(launches[0]["writes"][0]).parents[4]
        for path in sorted(run_dir.glob("steps/*/attempts/*/logs/stderr")):
            stderr[path.relative_to(run_dir).as_posix()] = path.read_text(errors="replace")[-300:]
    validation = [{"step": row.get("step_id"), "errors": row.get("errors"), "report": row.get("report")}
                  for row in _records(store, "step-validation")
                  if row.get("errors") or (row.get("report") or {}).get("passed") is False][-6:]
    print("VALIDATION_FAILURES=" + json.dumps(validation, default=str))
    print("PLAN_BIND_REFUSALS=" + json.dumps(_records(store, "step-plan-bind-refused"), default=str))
    return wave_a._where(store)[:2000] + " " + json.dumps(
        {"not_completed": held, "launches": journal, "stderr": stderr, "unmet": holes,
         "validation_failures": validation,
         "unmet_counts": counts,
         "authority_requests": [{k: row.get(k) for k in ("kind", "reason", "needed")}
                                for row in _records(store, "authority-request")]}, default=str)[:8000]


def _authority(store, kind):
    return [r for r in _records(store, "authority") if r.get("kind") == kind]


def test_wave_b_gate(run):
    store, summary = run
    # 1. Intake selected the analysis route, and its compiled plan is the bound controller plan.
    assert _unmet(store, "intake->route_select") == [], _where(store)
    selected = [r.get("route") for r in _records(store, "route")]
    assert selected and selected[-1] == "analysis", (selected, _where(store))
    plans = [r for r in _records(store, "plan") if r.get("blob") and r.get("source") != "judgment-planning"]
    plan = json.loads(store.get_blob(plans[-1]["blob"])) if plans else {}
    assert (plan.get("route") or {}).get("id") == "analysis", _where(store)
    # 2. The prepare phase and the plan review discharge every row CHECK-IN 1 needs; the authority resolves it.
    assert _unmet(store, "plan_review->checkin1") == [], _where(store)
    approvals = _authority(store, "approve_plan")
    assert approvals, ("CHECK-IN 1 was never resolved", _where(store))
    assert approvals[-1].get("label") == "operator_configured_machine", approvals[-1]
    assert approvals[-1].get("decision") == "approve", approvals[-1]
    # 3. The execute transition holds no unmet row.
    assert _unmet(store, "checkin1->execute") == [], _where(store)
    # 4. The smoke rung and the waypoint ran as materialised confined launches of the approved plan, never as worker
    #    sessions: the launch the step graph started is the one preparation bound (``route_analysis.launches``).
    operate = {s["id"] for s in plan["steps"] if s["kind"] == "operate"}
    finished = [r for r in _records(store, "step-launch") if r.get("phase") == "finished"]
    launched = {r["step_id"] for r in finished if r.get("exit_status") == 0 and r.get("backend")}
    assert {"recast.smoke", WAYPOINT} <= launched, ("no materialised operate launch", _where(store))
    print("OPERATE_DISPATCHES=" + json.dumps([r for r in _records(store, "step-dispatch")
          if r.get("step_id") in operate], default=str))
    print("COMPOSED_STATE=" + str(_where(store)))
    assert not operate & {r.get("step_id") for r in _records(store, "step-dispatch")}, "an operate step ran a worker"
    bound = {s["id"]: s for s in plan["steps"]}
    assert all((bound[sid].get("parameters") or {}).get("launch") for sid in launched & operate), launched
    # 5. CHECK-IN 2's declared seat reviewed the waypoint's exact outputs: a credited revise, one bounded correction
    #    round that re-ran the waypoint producer, then an accepted second round on the new subject.
    rounds = [row for row in store.scan("review") if row["record"].get("purpose") == "waypoint"]
    assert len(rounds) == 2, ([r["record"] for r in rounds], _where(store))
    first, second = (row["record"]["seats"][CI2_SEAT] for row in rounds)
    assert first["credited"] is True and first["verdict"] == "revise" and first["findings"], first
    assert second["credited"] is True and second["verdict"] == "accept", second
    assert rounds[0]["record"]["subject_sha256"] != rounds[1]["record"]["subject_sha256"]
    seats = [r for r in _records(store, "step-dispatch") if r.get("step_id") == CI2_STEP]
    assert len(seats) == 2 and {r["selection"]["transport_id"] for r in seats} == {wave_a.TRANSPORT}, seats
    waypoint = sorted(r.get("attempt") for r in _records(store, "step-outcome")
                      if r.get("step_id") == WAYPOINT and r.get("status") == "completed")
    assert waypoint == [1, 2], waypoint
    # 6. The GO is the authority's, binds the accepted round, and the waypoint's transition holds no unmet row.
    go = _authority(store, "go")
    assert go and go[-1].get("label") == "operator_configured_machine", (go, _where(store))
    assert ((go[-1].get("subject") or {}).get("pins") or {}).get("checkin2_review") == rounds[1]["id"], go[-1]
    assert _unmet(store, f"checkin2->execute[{WAYPOINT}]") == [], _where(store)
    # 7. Every approved step completed with its rows recorded: the run reaches execute->final_review.
    assert _records(store, "step-ledger-refused") == [], _records(store, "step-ledger-refused")
    assert "step-ledger-unmaterialised" not in json.dumps(_records(store, "step-outcome"))
    assert _unmet(store, "execute->final_review") == [], _where(store)


def test_positive_control_the_harness_drives_the_real_analysis_route(run):
    """The gate's harness reaches the real joins: if this fails, the gate's verdict is about the harness.

    Holds today: the services are the installed packages, intake selects the analysis route, the first prepare step
    runs through the real step graph on the qualified transport and its evidence is accepted by the route adapter,
    the census reaches the governed step, and the bounded end is the sink's honest qualified receipt.
    """
    store, summary = run
    absent = (graph._AbsentLedger, graph._AbsentAuthority, graph._AbsentSink, graph._AbsentInstructions,
              graph._AbsentJudgment, graph._AbsentConfine)
    for name in wave_a.SERVICES:
        found = graph.service(name)
        assert not isinstance(found, absent), name
        assert getattr(found, "__name__", None) == f"ravel.controller.{name}", (name, found)
    assert _unmet(store, "intake->route_select") == []
    assert [r.get("route") for r in _records(store, "route")][-1:] == ["analysis"]
    env = [r for r in _records(store, "step-observation") if r.get("step_id") == "env"]
    assert env and env[0].get("status") == "ok" and (env[0].get("tool_inventory") or {}).get("equal") is True, env
    completed = {r.get("step_id") for r in _records(store, "step-outcome") if r.get("status") == "completed"}
    assert "env" in completed, _where(store)
    assert any(r.get("step_id") == "inputs.census" for r in _records(store, "step-outcome")), _where(store)
    dispatched = _records(store, "step-dispatch")
    assert {r["selection"]["transport_id"] for r in dispatched} == {wave_a.TRANSPORT}
    assert {r["selection"]["model"] for r in dispatched} == {wave_a.MODEL}
    from ravel.controller import sink
    receipt = sink.receipt(store)
    labels = receipt.get("labels") or []
    assert summary["terminal"] is not None, summary
    assert receipt.get("label") == "qualified" and "QUALIFIED ENDING" in labels, receipt
    assert "NOT GOVERNED" not in labels and receipt.get("accepted") is not True, receipt


def test_positive_control_the_fictional_record_serves_the_census_and_the_acquisition(tmp_path, monkeypatch):
    """The stand-ins are sufficient: the installed census and data acquisition complete against the fictional
    record without the network, and the inert writer writes a launch's declared outputs where its attempt runs."""
    from ravel.cli import _draft_route
    from ravel.validation import validate_run_state
    from ravel.workflow import hepdata_fetch, resource_census
    requested = []
    _discovery(monkeypatch, requested)
    _, reading, _ = _draft_route(REQUEST.decode(), None, None)
    (tmp_path / "reading.json").write_text(json.dumps(reading))
    out = tmp_path / "run" / "inputs" / "resource_census.json"
    out.parent.mkdir(parents=True)
    assert resource_census.main(["--reading", str(tmp_path / "reading.json"), "--controller-output", str(out)]) == 0
    census = json.loads(out.read_text())
    assert any(record.get("rungs_ok") for record in census["records"]), census
    status, _, checks = validate_run_state.check_resource_census(
        str(tmp_path / "run"), {}, {"resource_census_path": "inputs/resource_census.json"}, "R", False)
    assert status != "FAIL", checks
    assert hepdata_fetch.main(["--inspire", RECORD, "--out", str(tmp_path / "hepdata"), "--download-likelihood",
                               "--tables"]) in (None, 0)
    manifest = json.loads((tmp_path / "hepdata" / "hepdata_manifest.json").read_text())
    assert {row["name"] for row in manifest["table_files"]} == {"Table 1", "Table 2"}, manifest
    assert requested and all(_published(url) is not None for url in requested if "refersto" not in url), requested
    # The inert writer: the documents bound into its argv, under its attempt's output root, stamped with the attempt.
    contract, _, _ = _draft_route(REQUEST.decode(), None, None)
    documents = _documents(routes.compile(selection.find("analysis"), reading, contract))
    route = documents["inputs.route"]["outputs/route_analysis.json"]
    assert set(route["launches"]) == {"recast.smoke", WAYPOINT, "run.full", "visualize.final"}
    attempt = tmp_path / "steps" / WAYPOINT / "attempts" / "2" / "outputs"
    attempt.mkdir(parents=True)
    import subprocess
    subprocess.run(route["launches"][WAYPOINT]["argv"], cwd=attempt, check=True)
    written = json.loads((attempt / "waypoint.json").read_text())
    assert written["kind"] == "inert-waypoint" and written["attempt"] == 2 and written["execution"], written


def test_the_run_samples_stacks_under_the_gil_while_worker_pools_churn():
    """The drive's periodic stacks come from the GIL-holding sampler: it reports the frames of nested pool
    workers that recurse and retire, and no part of this gate arms faulthandler's GIL-free watchdog."""
    import concurrent.futures
    import copy

    parked, release = threading.Semaphore(0), threading.Event()

    def nested(depth, hold=False):
        if depth == 0:
            if hold:
                # Event-driven, not timed: the worker stays inside its deep recursion until a sample is taken.
                parked.release()
                release.wait()
            return copy.deepcopy({"rows": [{"cells": list(range(4))} for _ in range(8)]})
        return nested(depth - 1, hold)

    class Signalled(io.StringIO):
        """The sampler's stream; each written sample sets ``written``."""
        written = threading.Event()

        def write(self, text):
            count = super().write(text)
            self.written.set()
            return count

    stream = Signalled()
    with _stack_samples(0.005, stream):
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            held = [pool.submit(nested, 120 + i, True) for i in range(4)]
            for _ in range(4):
                assert parked.acquire(timeout=60), "a pool worker never reached its nested frame"
            # The second write after every worker parked is a sample whose frames were taken after the parking.
            for _ in range(2):
                stream.written.clear()
                assert stream.written.wait(60), "the sampler wrote no sample while the workers were parked"
            release.set()
            [future.result() for future in held]
        # The pools keep starting and retiring threads under the sampler, as the controller's do.
        for _ in range(4):
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                list(pool.map(lambda i: [nested(120 + i) for _ in range(10)], range(8)))
    samples = stream.getvalue()
    assert samples.count("in nested") >= 3, samples[:2000]
    assert "Stack samples (0.005 s)" in samples and "(wave-b-stack-samples)" in samples, samples[:2000]
    assert not re.search(r"^\s*faulthandler\.dump_traceback_later\(", Path(__file__).read_text(), re.M)
