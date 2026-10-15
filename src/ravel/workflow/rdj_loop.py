"""Decision justification loop (RDJ §5.4): propose, interrogate, critique, revise, verify, authorize.

Gates invoke this loop; agents cannot opt out. Code computes the risk class from
the gate and the facts (an action kind, a rung or a declared factor only raises it;
lowering happens only through the gate's own policy list), commits the proposed
action before any challenge, generates every "why" challenge, verifies anchors,
applies the self-grounding and circularity rules, computes the affected set of a
revision and writes the receipt. Models judge only one hop (edge reviewer), the
whole case through a closed taxonomy (critic) and whether findings were resolved
(verifier). No model output can authorize: authorization is a code decision.

Authority never comes from a file the proposer can write. Run records:
``<rundir>/rdj/cases/<case_id>.json`` (the v2 case), ``rdj/state/<case_id>.json``
(loop state), ``rdj/journal/<case_id>.jsonl`` (a readable copy of the case journal),
``rdj/receipts/<receipt_id>.json`` and ``rdj/queue/`` (requests as work items).
Every save stores the case and state contents in RAVEL's custody store (``rdj_custody``)
and journals their digests there before the run copies are written; every load replays
the journal, so an edited case, state or journal is refused, and ``restore`` rebuilds the
run copies after an interrupted save. Input snapshots, user text, human decisions,
registered receipts, role reservations and RDJ receipts live in custody too.

Criticism is evidence-classed: a finding holds authorization only when its
``new_receipt`` or ``code_check`` basis verifies (``critic_basis``), or while a
discriminating test it requested is pending or after that test upheld it
(``finding_status``). ``cited`` and ``opinion`` findings are advisory and are listed in
the receipt. ``support_closure`` and ``common_mode_anchors`` are recomputable checks.

Role identity comes from receipts, never from what a model says. A dispatcher
returns a reference to a host-written record: an ``agent_graph`` model receipt
(``AgentHostDispatcher``) or a worker receipt registered by the worker dispatcher
. Actor, session and model family are read from it; the attestation
label is the one the registering dispatcher verified (``decision_case.label_for``), never the
receipt's own claim. A ``code_check`` verifies only on a registered failed check result or a
failed validation stage. A withdrawn test, a reopened action and a human approval each need a
user decision recorded in custody; steering text that mentions an action decides nothing.
Callers of the gate read the authorizing receipt through ``authorizing_receipt``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import decision_case as dc
from . import evidence_queue
from . import rdj_anchor as anchor_check
from . import rdj_custody as custody
from .state_io import atomic_json, file_lock, read_json

try:  # The decision gate owns the shared error type; keep the identical shape until it lands.
    from .decision_gate import GateError
except ImportError:  # pragma: no cover - exercised only before decision_gate exists
    @dataclass(frozen=True)
    class GateError:
        code: str
        gate: str
        provider: str
        message: str
        fix: str
        pins: tuple = ()

PROVIDER = "rdj"
ROOT = "action"
RANK = {c: i for i, c in enumerate(dc.CLASSES)}
BLOCKING_CRITIQUE = dc.BLOCKING_MATERIALITY
DISAGREEMENT_CODES = ("unsupported_claim", "decision_does_not_follow", "contradiction", "chain_stopped_early",
                      "circular_justification", "irrelevant_support", "post_hoc_rationalization")
CRITIC_CARD = {"approve_plan": "plan-critic", "checkin2_accept": "physics-critic", "delivery": "physics-critic",
               "final_task": "physics-critic"}
VERIFIER_CARD = {"checkin2_accept": "skeptical-verifier", "delivery": "skeptical-verifier",
                 "final_task": "skeptical-verifier"}
AGENT_ROLES = {"edge_reviewer": "rdj_edge_reviewer", "critic": "rdj_critic", "verifier": "rdj_verifier"}
# Execution observations and the label each earns; ``transport_attested_cli`` earns it only with a
# verified label (``decision_case.label_for``), which every reader applies.
OBSERVED_ATTESTATION = {**dc.OBSERVED_LABELS, "transport_attested_cli": "transport_attested"}
NODE_FIELDS = {"id", "kind", "assertion", "rationale", "material", "confidence", "recommends_choice",
               "assumptions", "unknowns", "anchors"}
ANCHOR_FIELDS = {"kind", "binding", "locator", "value", "quantity"}
CONFIDENCE_LEVEL = {"high": 3, None: 2, "medium": 2, "low": 1}  # undeclared counts as medium
EDGE_FINDING = "E:"


class CaseInvalidated(ValueError):
    """The committed action changed; a new proposal commit (a new case) is required."""


class CaseTampered(ValueError):
    """The case, its state or its journal differs from RAVEL's custody journal."""


class IndependenceError(ValueError):
    """A role output came from a session or actor that the policy requires to be distinct."""


class OpenItems(ValueError):
    """Authorization refused by code; ``items`` names each open item."""

    def __init__(self, items):
        self.items = items
        super().__init__("; ".join(item["message"] for item in items))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir(rundir, name):
    return Path(rundir) / "rdj" / name


def _case_path(rundir, case_id):
    if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", case_id):
        raise ValueError("invalid case id")
    return _dir(rundir, "cases") / (case_id + ".json")


def _state_path(rundir, case_id):
    return _dir(rundir, "state") / (case_id + ".json")


def _lock(rundir, case_id):
    return file_lock(_dir(rundir, "locks") / (case_id + ".lock"))


def canonical_gate(name):
    """The policy decision point for a gate name or alias; unknown names are refused."""
    pol = anchor_check.policy()
    if name in pol["gates"]:
        return name
    if name in pol["gate_aliases"]:
        return pol["gate_aliases"][name]
    raise ValueError(f"rdj_unknown_gate: {name!r} is not a decision point in the policy")


# ---------------------------------------------------------------- journal, custody and replay

def _journal(rundir, case_id, event, data):
    """Append one event to the custody journal and its readable run copy; returns the line."""
    line = custody.append(rundir, "journal-" + case_id, {"event": event, "data": data})
    path = _dir(rundir, "journal") / (case_id + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n")
    return line


def _normal(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _commit(rundir, case, state, event, data=None):
    """Save the case and state: contents to custody, then the journal line, then the run copies.
    An interruption leaves the run copies at most one save behind the journal; ``restore``
    rebuilds them from custody."""
    case, state = _normal(dc.validate_case_v2(case)), _normal(state)
    case_sha, state_sha = custody.put_blob(rundir, case), custody.put_blob(rundir, state)
    _journal(rundir, case["case_id"], event, {**(data or {}), "case_sha256": case_sha, "state_sha256": state_sha})
    atomic_json(_case_path(rundir, case["case_id"]), case)
    atomic_json(_state_path(rundir, case["case_id"]), state)


def restore(rundir, case_id):
    """Rebuild a case's run copies (case, state and readable journal) from RAVEL custody, after an
    interrupted save or a damaged copy. Custody is the authority; nothing in the run is trusted."""
    rundir = Path(rundir)
    with _lock(rundir, case_id):
        try:
            lines = custody.rows(rundir, "journal-" + case_id)
        except custody.CustodyError as exc:
            raise CaseTampered(f"custody journal of {case_id} does not verify: {exc}") from None
        saved = [line["record"]["data"] for line in lines if "case_sha256" in line["record"]["data"]]
        if not saved:
            raise CaseTampered(f"custody holds no saved state for case {case_id}")
        case = custody.get_blob(rundir, saved[-1]["case_sha256"])
        state = custody.get_blob(rundir, saved[-1]["state_sha256"])
        atomic_json(_case_path(rundir, case_id), case)
        atomic_json(_state_path(rundir, case_id), state)
        path = _dir(rundir, "journal") / (case_id + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines),
                        encoding="utf-8")
    return status(rundir, case_id)


def _replay(rundir, case_id):
    try:
        lines = custody.rows(rundir, "journal-" + case_id)
    except custody.CustodyError as exc:
        raise CaseTampered(str(exc)) from None
    if not lines or lines[0]["record"]["event"] != "proposal_committed":
        raise CaseTampered(f"case {case_id} has no committed proposal in RAVEL custody")
    path = _dir(rundir, "journal") / (case_id + ".jsonl")
    copy = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.is_file() else []
    if copy != lines:
        raise CaseTampered("the run journal differs from RAVEL's custody journal")
    return lines


def _load(rundir, case_id):
    """Load a case and its state, replaying the journal: an edited file is refused."""
    case = read_json(_case_path(rundir, case_id))
    state = read_json(_state_path(rundir, case_id))
    if case.get("schema_version") != 2 or state.get("schema_version") != 1 or state.get("kind") != "rdj-case-state":
        raise ValueError("unknown decision-justification case or state version")
    lines = _replay(rundir, case_id)
    data = lines[0]["record"]["data"]
    point = case.get("decision_point", {})
    committed = {"gate": point.get("gate"), "action_kind": point.get("action_kind"),
                 "summary": point.get("action", {}).get("summary"), "digest": point.get("action", {}).get("digest"),
                 "pins": point.get("action", {}).get("pins")}
    if any(data[k] != v for k, v in committed.items()) or case.get("input_artifacts", []) != data.get(
            "input_artifacts", []) or case["proposal"]["committed_event"] != lines[0]["digest"] \
            or case["risk"]["policy"]["sha256"] != data["policy_sha256"] or state.get("proposer") != data["proposer"] \
            or RANK.get(case["risk"]["class"], -1) < RANK[data["class"]] or state.get("commit_ns") != lines[0]["ns"]:
        raise CaseTampered("the case differs from its committed proposal")
    saved = [line["record"]["data"] for line in lines if "case_sha256" in line["record"]["data"]]
    if not saved or saved[-1]["case_sha256"] != dc.jdigest(case) or saved[-1]["state_sha256"] != dc.jdigest(state):
        raise CaseTampered("the case or its state differs from the last journaled save")
    return dc.validate_case_v2(case), state, lines


# ---------------------------------------------------------------- risk class

def _raise(cls, by=1):
    return dc.CLASSES[min(RANK[cls] + by, len(dc.CLASSES) - 1)]


def _at_least(cls, floor):
    return cls if RANK[cls] >= RANK[floor] else floor


def _custody_receipts(rundir):
    try:
        return [row["record"] for row in custody.rows(rundir, "receipts")]
    except custody.CustodyError:
        return []


def _accepted_before(rundir, action_kind, route):
    """A custody-recorded authorize receipt of class R1 or above for this kind and route."""
    for row in _custody_receipts(rundir):
        if row["outcome"] != "authorize":
            continue
        try:
            case, _, _ = _load(rundir, row["case_id"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if RANK[case["risk"]["class"]] >= RANK["R1"] and case["decision_point"]["action_kind"] == action_kind \
                and case["risk"]["computed_factors"].get("route") == route:
            return True
    return False


COST_RECORD = "inputs/cost_preflight.json"


def _cost_facts(rundir):
    """Points and walltime from ``inputs/cost_preflight.json``, read only when its bytes are the
    ones RAVEL's run_init snapshot recorded or an output of a registered, current tool stage
    (a later snapshot alone never vouches for them). An incomplete or uncalibrated record
    (no integer point count or no numeric walltime range) is unknown: None."""
    path = Path(rundir) / COST_RECORD
    if not path.is_file() or path.is_symlink():
        return None
    current = anchor_check.sha256_file(path)
    try:
        trusted = custody.snapshot_digest(rundir, COST_RECORD, event="run_init") == current or \
            anchor_check.verify_pin(rundir, {"path": COST_RECORD, "sha256": current},
                                    context={"rundir": str(rundir), "input_snapshot": None, "generated": [],
                                             "action_pins": []}) == "external"
        record = read_json(path) if trusted else None
    except (custody.CustodyError, OSError, ValueError):
        return None
    if not isinstance(record, dict) or type(record.get("points")) is not int:
        return None
    wall = record.get("walltime_h")
    if not (isinstance(wall, list) and wall and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                    for v in wall)):
        return None
    facts = {"points": record["points"], "walltime_hours": max(wall)}
    if isinstance(record.get("spend_usd"), (int, float)) and not isinstance(record["spend_usd"], bool):
        facts["spend_usd"] = record["spend_usd"]
    return facts


def compute_class(rundir, gate, action, facts=None, declared=None):
    """The class from policy, gate and facts. An action kind, rung, fact, declared factor or the
    caller's ``action["floor"]`` only raises it. Lowering needs a kind in the gate's ``lowerable_kinds`` (a rung lowers only with
    such a kind, and only through ``lowerable_rungs``), is never applied under a gate alias in
    ``non_lowering_aliases`` (bulk, scan), and is void once a consequence fact fires."""
    pol = anchor_check.policy()
    named = gate
    gate = canonical_gate(gate)
    rule = pol["gates"][gate]
    caller, declared = dict(facts or {}), dict(declared or {})
    base = rule["class"]
    factors = {"gate": gate, "gate_class": base}
    kind, rung = action.get("kind"), action.get("rung")
    kind_class, rung_class = pol["action_kinds"].get(kind), pol["rungs"].get(rung)
    raising = []
    for label, value in (("action_kind_class", kind_class), ("rung_class", rung_class)):
        if value is not None and RANK[value] > RANK[base]:
            raising.append(value)
            factors[label] = value
    computed = _cost_facts(rundir)
    merged = {k: max(caller.get(k) or 0, (computed or {}).get(k) or 0)
              for k in ("points", "walltime_hours", "spend_usd")}
    limits, consequence = pol["high_consequence"], []
    if merged["points"] >= limits["points_at_least"]:
        consequence.append("points")
    if merged["walltime_hours"] >= limits["walltime_hours_at_least"]:
        consequence.append("walltime")
    if merged["spend_usd"] > limits["spend_usd_above"]:
        consequence.append("spend")
    cls = base
    lowering = [(kind_class, kind)] if kind in rule.get("lowerable_kinds", ()) and kind_class is not None else []
    if lowering and rung_class is not None:
        lowering = lowering + [(rung_class, rung)] if rung in rule.get("lowerable_rungs", ()) else []
    if lowering and not consequence and named not in pol.get("non_lowering_aliases", ()):
        lowest = min(lowering, key=lambda row: RANK[row[0]])
        if RANK[lowest[0]] < RANK[base]:
            cls, factors["lowered_by"] = lowest
    for value in raising:
        cls = _at_least(cls, value)
    if consequence:
        cls = _raise(cls)
        factors["high_consequence"] = consequence
    if rule.get("consequence_facts") and computed is None and cls != "R0":
        cls = _raise(cls)
        factors["consequence_unknown"] = True
    if rule["irreversible"] or action.get("kind") in pol["irreversible_kinds"]:
        cls = _at_least(cls, "R3")
        factors["irreversible"] = True
    if caller.get("scope_change"):
        cls = _at_least(cls, "R3")
        factors["scope_change"] = True
    route = caller.get("route") or action.get("route")
    if route is not None:
        factors["route"] = route
    if caller.get("novel_method") or (route is not None and not _accepted_before(rundir, action.get("kind"), route)):
        cls = _raise(cls)
        factors["novelty"] = True
    if declared.get("class") is not None:
        if declared["class"] not in dc.CLASSES:
            raise ValueError("declared class must be R0-R3")
        cls = _at_least(cls, declared["class"])
    if "floor" in action:  # A caller's floor (review_points' risk class) only raises the class.
        floor = action["floor"]
        if not isinstance(floor, str) or floor not in dc.CLASSES:
            raise ValueError("action floor must be one of R0-R3")
        factors["floor"] = floor
        cls = _at_least(cls, floor)
    return cls, factors


# ---------------------------------------------------------------- opening a case

def _pin_ok(rundir, pin):
    try:
        path, _ = anchor_check.inside(rundir, pin["path"])
    except anchor_check.AnchorError:
        return False
    return anchor_check.sha256_file(path) == pin["sha256"]


def action_digest(pins):
    """The digest of the bytes an action acts on: one pin's sha256, or the digest of all pins."""
    return pins[0]["sha256"] if len(pins) == 1 else dc.jdigest(sorted(pins, key=lambda p: p["path"]))


def _actor_of(proposer):
    author = dc.actor({k: proposer.get(k) for k in ("actor_id", "session_receipt", "attestation")}, "proposer")
    if author["session_receipt"] is None:
        raise ValueError("the proposer names its session receipt; independence is checked against it")
    return author


def _input_artifacts(rundir, artifacts):
    out = []
    for artifact in artifacts or ():
        if type(artifact) is not dict or artifact.get("role") not in dc.INPUT_ARTIFACT_ROLES:
            raise ValueError(f"an input artifact has a role from {dc.INPUT_ARTIFACT_ROLES}")
        pin = {"path": artifact.get("path"), "sha256": artifact.get("sha256")}
        dc.binding(pin)
        _, rel = anchor_check.inside(rundir, pin["path"])
        if not _pin_ok(rundir, pin):
            raise ValueError(f"input artifact does not match its bytes: {pin['path']}")
        out.append({"role": artifact["role"], "path": rel, "sha256": pin["sha256"]})
    return out


def _receipt_rows(rundir, gate, digest, outcome=None):
    return [r for r in custody.rows(rundir, "receipts") if r["record"]["gate"] == gate
            and r["record"]["action_digest"] == digest and (outcome is None or r["record"]["outcome"] == outcome)]


def _reopened_after(rundir, digest, ns):
    """A user reopened the action after ``ns``: a recorded reopen decision. Steering that merely
    mentions the digest reopens nothing."""
    return custody.last_reopen_ns(rundir, digest) > ns


def _escalation_open(rundir, gate, digest, *, exclude=None):
    """The latest escalate receipt for this gate and action that no user decision reopened, or None."""
    rows = [r for r in _receipt_rows(rundir, gate, digest, "escalate") if r["record"]["case_id"] != exclude]
    return rows[-1] if rows and not _reopened_after(rundir, digest, rows[-1]["ns"]) else None


def _abandoned_reason(case, state):
    """Why a case without a receipt still holds the action: an open blocking finding or a blocking
    edge verdict, or a spent revision budget with findings pending; None when nothing holds."""
    if state["invalidated"]:
        return None
    pending = _pending_findings(case, state)
    holding = [f for f in _findings(case).values() if finding_status(case, state, f) == "pending_test"]
    rounds = anchor_check.policy()["classes"][case["risk"]["class"]]["revision_rounds"]
    if pending or holding:
        spent = " after its revision budget was spent" if len(case["revisions"]) >= rounds else ""
        return "abandoned with open findings " + ", ".join(sorted(f["id"] for f in pending + holding)) + spent
    return None


def _escalate_abandoned(rundir, gate, digest):
    """Write the escalation of every earlier case of this action that was left with open findings."""
    decided = {r["record"]["case_id"] for r in _receipt_rows(rundir, gate, digest)}
    for row in custody.rows(rundir, "cases"):
        record = row["record"]
        if record["gate"] != gate or record["digest"] != digest or record["case_id"] in decided:
            continue
        with _lock(rundir, record["case_id"]):
            try:
                case, state, _ = _load(rundir, record["case_id"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            reason = _abandoned_reason(case, state)
            if reason:
                _write_receipt(rundir, case, state, "escalate", 0, reason=reason)


def open_case(rundir, gate, action, proposer, *, facts=None, declared=None, tuning=None, input_artifacts=None):
    """Commit the proposed action as the first journal event and create the case; returns its id.

    Runs under the run's custody lock: the case budget, the escalation check (an earlier case of
    the same action left with open findings is escalated here) and the reservation are one step."""
    rundir = Path(rundir)
    if type(action) is not dict:
        raise ValueError("action must be an object")
    named, gate = gate, canonical_gate(gate)
    dc.text(action.get("kind"), "action kind")
    dc.text(action.get("summary"), "action summary")
    dc._sha(action.get("digest"), "action digest")
    pins = action.get("pins")
    if not isinstance(pins, list) or not pins:
        raise ValueError("an action names at least one pin inside the run: the bytes it acts on")
    normalized = []
    for pin in pins:
        dc.binding(pin)
        _, rel = anchor_check.inside(rundir, pin["path"])
        if not _pin_ok(rundir, pin):
            raise ValueError(f"action pin does not match its bytes: {pin['path']}")
        normalized.append({"path": rel, "sha256": pin["sha256"]})
    if action["digest"] != action_digest(normalized):
        raise ValueError("the action digest must equal the pinned bytes' digest (one pin's sha256, or jdigest of pins)")
    author = _actor_of(proposer)
    artifacts = _input_artifacts(rundir, input_artifacts)
    pol = anchor_check.policy()
    digest = action["digest"]
    with custody.run_lock(rundir):
        _escalate_abandoned(rundir, gate, digest)
        if _escalation_open(rundir, gate, digest):
            raise ValueError("this action was escalated; a new case needs a recorded user decision that reopens it")
        declared = dict(declared or {})
        if proposer.get("confidence") is not None:
            declared["confidence"] = proposer["confidence"]
        cls, factors = compute_class(rundir, named, action, facts, declared)
        choice = action["kind"] in pol["choice_kinds"] or bool(pol["gates"][gate].get("choice"))
        case_id = f"{gate}-{digest[:12]}-{uuid.uuid4().hex[:8]}"
        policy_pin = anchor_check.policy_pin()
        point = {"gate": gate, "action_kind": action["kind"],
                 "action": {"summary": action["summary"], "digest": digest, "pins": normalized}}
        if tuning is not None:
            point["tuning"] = dict(tuning)
        case = {"schema_version": 2, "kind": dc.CASE_KIND, "case_id": case_id, "rundir": str(rundir.resolve()),
                "decision_point": point,
                "risk": {"class": cls, "computed_factors": factors, "declared_factors": declared, "policy": policy_pin},
                "proposal": {"node_id": ROOT, "committed_event": "0" * 64},
                "nodes": [{"id": ROOT, "kind": "action", "assertion": action["summary"],
                           "rationale": proposer.get("rationale") or "The proposed action, committed before any challenge.",
                           "material": True, "round": 0, "author": author, "confidence": proposer.get("confidence"),
                           "anchors": [], "assumptions": [], "unknowns": [], "recommends_choice": choice}],
                "edges": [], "anchors": [], "critique": None, "revisions": [], "verification": None}
        if artifacts:
            case["input_artifacts"] = artifacts
        dc.validate_case_v2(case)  # Refuse a malformed proposal before anything is committed.
        since = custody.last_reopen_ns(rundir, digest)
        cap = pol["budgets"]["max_cases_per_action"]

        def budget(rows):
            count = sum(1 for r in rows if r["record"]["gate"] == gate and r["record"]["digest"] == digest
                        and r["ns"] > since)
            return (f"this action already has {count} cases; the per-action case budget is spent (a recorded "
                    "user decision can reopen it)") if count >= cap else None
        custody.append(rundir, "cases", {"case_id": case_id, "gate": gate, "digest": digest, "proposer": author},
                       check=budget)
        committed = _journal(rundir, case_id, "proposal_committed",
                             {"gate": gate, "action_kind": action["kind"], "summary": action["summary"],
                              "digest": digest, "pins": normalized, "proposer": author, "class": cls,
                              "policy_sha256": policy_pin["sha256"], **({"input_artifacts": artifacts}
                                                                         if artifacts else {})})
        case["proposal"]["committed_event"] = committed["digest"]
        state = {"schema_version": 1, "kind": "rdj-case-state", "case_id": case_id, "proposer": author,
                 "commit_ns": committed["ns"], "authors": [author], "anchor_status": {}, "anchor_reasons": {},
                 "observed": {}, "usage": {"model_calls": 0, "by_role": {}}, "calls": [], "invalidated": None,
                 "blocking": {}, "edge_reviews": {}, "reviewer_sessions": [], "critic_sessions": [],
                 "critic_revision": None, "critic_digest": None, "verified_digest": None, "reopened": [],
                 "disagreement": [], "choice_marked": [], "open_unknowns": [], "finding_basis": {},
                 "finding_tests": {}, "support_closure": None, "budget_exhausted": False, "budget_reason": None,
                 "self_attested_verifier": False, "opened_utc": _now()}
        _case_path(rundir, case_id).parent.mkdir(parents=True, exist_ok=True)
        _state_path(rundir, case_id).parent.mkdir(parents=True, exist_ok=True)
        state["support_closure"] = _closure(case, state)
        _commit(rundir, case, state, "case_created")
    return case_id


# ---------------------------------------------------------------- graph helpers

def _nodes(case):
    return {n["id"]: n for n in case["nodes"]}


def _parents(case):
    parents = {n["id"]: [] for n in case["nodes"]}
    for edge in case["edges"]:
        parents[edge["child"]].append(edge["parent"])
    return parents


def _ancestors(case, node_ids):
    parents, seen, stack = _parents(case), set(), list(node_ids)
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in parents:
            continue
        seen.add(node_id)
        stack.extend(parents[node_id])
    return seen


def _blocked(edge):
    review = edge["review"]
    return review is not None and (review["entailment"] == "fails" or review["relevance"] == "irrelevant")


def _board_dirs(case):
    """Research-board content: everything beside the case's ``board_head`` (the board's journal head)."""
    dirs = []
    for artifact in case.get("input_artifacts", ()):
        if artifact["role"] == "board_head":
            parent = Path(artifact["path"]).parent.as_posix()
            dirs.append(artifact["path"] if parent in ("", ".") else parent)
    return dirs


def _context(rundir, case, state):
    return {"rundir": str(rundir), "input_snapshot": custody.input_snapshot(rundir, before_ns=state["commit_ns"]),
            "generated": sorted(anchor_check.generated_paths(rundir)), "generated_dirs": _board_dirs(case),
            "action_pins": case["decision_point"]["action"]["pins"]}


def _human(rundir, case):
    return bool(custody.approvals(rundir, case["case_id"], case["decision_point"]["action"]["digest"]))


def _unknown_request(unknown):
    return unknown["request"] or {"kind": "evidence", "description": ("Answer: " + unknown["question"])[:dc.MAX_DESCRIPTION]}


def _answered(rundir, item, context):
    """A work item counts as answered only when it is ``done`` and every resolution pin verifies
    ``external`` now (an external input, or the output of a registered, current tool stage).
    The queue file itself is run-writable, so its status alone proves nothing."""
    pins = (item.get("resolution") or {}).get("pins") if item.get("status") == "done" else None
    return bool(pins) and all(anchor_check.verify_pin(rundir, pin, context=context) == "external" for pin in pins)


def evidence_request_answered(rundir, item_id):
    """Public review-point seam: missing or edited queue status never resolves a finding.

    Reuse RDJ's external-pin check and the original case's pre-commit input
    snapshot when available; standalone reviews use the latest vouched inputs.
    """
    try:
        item = next((i for i in evidence_queue.items(rundir) if i['item_id'] == item_id), None)
        if item is None:
            return False
        case_path = Path(rundir) / 'rdj/cases' / (item['case_id'] + '.json')
        if case_path.exists():
            case, state, _ = _load(rundir, item['case_id'])
            context = _context(rundir, case, state)
        else:
            context = {'rundir': str(rundir), 'input_snapshot': custody.input_snapshot(rundir),
                       'generated': sorted(anchor_check.generated_paths(rundir)), 'action_pins': []}
        return _answered(rundir, item, context)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _open_unknowns(rundir, case, context=None):
    """Material nodes whose unknowns have no answered work item."""
    context = context or {"rundir": str(rundir), "input_snapshot": None, "generated": [], "action_pins":
                          case["decision_point"]["action"]["pins"]}
    done = {(i["target"], dc.jdigest(i["request"])) for i in evidence_queue.items(rundir, case_id=case["case_id"])
            if _answered(rundir, i, context)}
    return sorted(n["id"] for n in case["nodes"] if n["material"] and any(
        (n["id"], dc.jdigest(_unknown_request(u))) not in done for u in n["unknowns"]))


def _receipt_answer(rundir, pin, context):
    """Whether a resolution pin is a receipt: a registered worker receipt with its registered bytes,
    or an output of a registered, current stage receipt of a recognized tool (an input file is not)."""
    try:
        _, rel = anchor_check.inside(rundir, pin["path"])
        if custody.worker_registered(rundir, rel, pin["sha256"]) and _pin_ok(rundir, pin):
            return True
    except (anchor_check.AnchorError, custody.CustodyError, OSError, ValueError, KeyError, TypeError):
        return False
    return anchor_check.verify_pin(rundir, pin, context={**context, "input_snapshot": None}) == "external"


def _finding_tests(rundir, case, state, context):
    """The state of each discriminating test a finding requested: pending, upholds, refutes or withdrawn.

    The queue file is run-writable, so its status never decides alone. ``withdrawn`` needs a recorded
    user decision withdrawing the finding, or the critic session that raised it withdrawing it in a
    registered receipt. A verdict counts only when the resolution pins a receipt (``_receipt_answer``)
    and every pin verifies now. Anything else is ``pending``."""
    items = {(i["target"], dc.jdigest(i["request"])): i for i in evidence_queue.items(rundir, case_id=case["case_id"])
             if i["source"] == "critic_finding"}
    withdrawn = custody.withdrawals(rundir, case["case_id"], case["decision_point"]["action"]["digest"]) \
        | set(state.get("critic_withdrawn") or ())
    tests = {}
    for finding in _findings(case).values():
        request = finding["request"]
        if request is None or request["kind"] not in dc.TEST_REQUESTS:
            continue
        item = items.get((finding["id"], dc.jdigest(request)))
        tests[finding["id"]] = "pending"
        if finding["id"] in withdrawn:
            tests[finding["id"]] = "withdrawn"
        elif item is not None and item["status"] == "done" and item["resolution"]["pins"]:
            receipts = [_receipt_answer(rundir, pin, context) for pin in item["resolution"]["pins"]]
            if any(receipts) and all(r or anchor_check.verify_pin(rundir, pin, context=context) == "external"
                                     for r, pin in zip(receipts, item["resolution"]["pins"])):
                tests[finding["id"]] = item["resolution"].get("verdict") or "pending"
    return tests


def finding_status(case, state, finding):
    """``blocking``, ``pending_test`` or ``advisory`` under the evidence-class rule.

    Blocking: an A/B finding whose ``new_receipt`` or ``code_check`` basis verified when the
    critic returned it, or whose requested discriminating test upheld it. Pending: its test has
    not answered. Everything else (``cited`` and ``opinion`` without a test, an unverified
    basis, a refuted or withdrawn test) is advisory and listed in the receipt."""
    if not dc.may_block(finding):
        return "advisory"
    if finding["evidence_class"] in dc.BLOCKING_EVIDENCE and \
            state.get("finding_basis", {}).get(finding["id"]) == "verified":
        return "blocking"
    test = state.get("finding_tests", {}).get(finding["id"])
    if test == "pending":
        return "pending_test"
    return "blocking" if test == "upholds" else "advisory"


def _failed_check(value, producer):
    """Whether a check-result record reports a failure from a recognized check: a registered
    validator module or a shipped invariant, matching ``producer`` when one is given."""
    if type(value) is not dict or value.get("kind") != custody.CHECK_RESULT_KIND or value.get("status") != "failed":
        return False
    named = value.get("producer")
    if not isinstance(named, str) or (producer is not None and named != producer):
        return False
    if named.startswith("invariant:"):
        return named[len("invariant:"):] in anchor_check.invariant_rows()
    return named in anchor_check.policy()["measurement_validators"].values()


def _check_pins_current(rundir, value):
    pins = value.get("pins")
    if not isinstance(pins, list):
        return False
    for pin in pins:
        try:
            dc.binding(pin)
        except (ValueError, TypeError, KeyError):
            return False
        if not _pin_ok(rundir, pin):
            return False
    return True


def _code_check_locator(rundir, locator, context):
    """None when ``locator`` names a failed recognized check for the current bytes, else the reason."""
    if locator.startswith("check:"):
        try:
            value = custody.check_result(rundir, locator[len("check:"):])
        except (custody.CustodyError, OSError, ValueError, TypeError) as exc:
            return str(exc)
        if not _failed_check(value, None):
            return f"{locator} is not a failed result of a registered validator or shipped invariant"
        if not _check_pins_current(rundir, value):
            return f"{locator} was computed for bytes that have since changed"
        return None
    if locator.startswith("stage:"):
        try:
            record = anchor_check.stage_receipt(rundir, locator, context)
        except (anchor_check.AnchorError, anchor_check.Generated, OSError, ValueError, KeyError, TypeError) as exc:
            return str(exc)
        made_by = anchor_check.producer(rundir, record)
        validators = anchor_check.policy()["measurement_validators"].values()
        if made_by is None or made_by[0] != "module" or made_by[1] not in validators:
            return f"{locator} is not a stage of a registered validator"
        root = Path(rundir).resolve()
        for key, entry in (record.get("output_snapshot") or {}).items():
            for row in (entry or {}).get("files", ()):
                path = Path(key) if row.get("name") == "." else Path(key) / row.get("name", "")
                path = path if path.is_absolute() else root / path
                try:
                    if anchor_check.sha256_file(path) != row.get("sha256"):
                        continue
                    value = json.loads(path.read_bytes())
                except (OSError, ValueError):
                    continue
                if _failed_check(value, made_by[1]) and _check_pins_current(rundir, value):
                    return None
        return f"{locator} reports no failed check"
    return f"locator {locator} names no check result (check:<id>) or validation stage (stage:<name>:<attempt>)"


def critic_basis(rundir, case, finding, context=None):
    """check:critic_basis: ``verified`` when the finding's blocking evidence is a receipt, else the reason.

    The public predicate for every provider that weighs criticism (``case`` is unused and may be None).
    A ``new_receipt`` finding verifies when a locator names a registered, current stage receipt of a
    recognized tool. A ``code_check`` finding verifies only when a locator is ``check:<id>``, a
    custody-registered result with ``status: failed`` from a registered validator or shipped
    invariant whose pins match the current bytes, or ``stage:<name>:<attempt>``, a registered,
    current stage of a registered validator whose output reports such a failure. Run files and case
    elements are cited, not checked."""
    locators = finding["evidence_locators"]
    if finding["evidence_class"] == "new_receipt":
        for locator in locators:
            if not locator.startswith("stage:"):
                continue
            try:
                record = anchor_check.stage_receipt(rundir, locator, context)
            except (anchor_check.AnchorError, anchor_check.Generated, OSError, ValueError, KeyError, TypeError):
                continue
            if anchor_check.producer(rundir, record) is not None:
                return "verified"
        return "no locator names a registered, current stage receipt of a recognized tool"
    if finding["evidence_class"] == "code_check":
        if not locators:
            return "a code check names the check result that failed"
        reasons = []
        for locator in locators:
            reason = _code_check_locator(rundir, locator, context)
            if reason is None:
                return "verified"
            reasons.append(reason)
        return "; ".join(reasons)[:dc.MAX_REASON]
    return "not a blocking evidence class"


def _closure(case, state):
    """check:support_closure: the unknown and conflict sets closed over typed support. A claim is
    unknown (in conflict) when it carries an open unknown (a conflicting anchor) or is supported,
    through ``supports`` edges, by a claim that is. Canonical, so it recomputes byte-identically."""
    pol = anchor_check.policy()
    parents = {}
    dependencies = []
    for edge in case["edges"]:
        if edge["relation"] == "supports":
            parents.setdefault(edge["child"], []).append(edge["parent"])
            dependencies.append([edge["parent"], edge["child"]])

    def up(seed):
        seen, stack = set(), list(seed)
        while stack:
            node_id = stack.pop()
            if node_id not in seen:
                seen.add(node_id)
                stack.extend(parents.get(node_id, ()))
        return sorted(seen)
    conflicts = anchor_check.conflicting_nodes(case, state["anchor_status"], pol["conflict_default_relative_tolerance"],
                                               state["observed"])
    return {"schema_version": 1, "unknown": up(state["open_unknowns"]), "conflict": up(conflicts),
            "dependencies": sorted(dependencies)}


def _chain(case):
    """``{node: every node it reaches through supports edges}``."""
    out = {}
    for edge in case["edges"]:
        if edge["relation"] == "supports":
            out.setdefault(edge["parent"], []).append(edge["child"])
    memo = {}

    def below(node_id):
        if node_id not in memo:
            memo[node_id] = set()
            for child in out.get(node_id, ()):
                memo[node_id] |= {child} | below(child)
        return memo[node_id]
    return {n["id"]: below(n["id"]) for n in case["nodes"]}


def _common_mode(case, state):
    """check:common_mode_anchor: at the policy's classes and gates (R3, delivery), a source read by
    externally verified anchors of two or more material claims that are not on one support chain,
    where those claims have no independent external source of their own."""
    rule = anchor_check.policy()["common_mode"]
    if case["risk"]["class"] not in rule["classes"] and case["decision_point"]["gate"] not in rule["gates"]:
        return []
    anchors = {a["id"]: a for a in case["anchors"]}
    sources = {}
    for node in case["nodes"]:
        if node["id"] == ROOT or not node["material"] or node["kind"] == "alternative":
            continue
        own = set()
        for aid in node["anchors"]:
            anchor = anchors[aid]
            if state["anchor_status"].get(aid) == "external" and anchor["kind"] in rule["anchor_kinds"]:
                source = anchor_check.evidence_source(anchor)
                if source is not None:
                    own.add(source)
        sources[node["id"]] = own
    users = {}
    for node_id, own in sources.items():
        for source in own:
            users.setdefault(source, set()).add(node_id)
    shared = {s for s, claims in users.items() if len(claims) >= 2}
    reach = _chain(case)
    flagged = []
    for source in sorted(shared, key=lambda s: json.dumps(s)):
        claims = sorted(c for c in users[source] if sources[c] <= shared)
        unrelated = [c for c in claims if any(o != c and o not in reach[c] and c not in reach[o] for o in claims)]
        if len(unrelated) >= 2:
            flagged.append({"source": list(source), "claims": unrelated})
    return flagged


# ---------------------------------------------------------------- refresh and frontier

def _invalidate(rundir, case, state, reason):
    state["invalidated"] = reason
    _commit(rundir, case, state, "case_invalidated", {"reason": reason})
    raise CaseInvalidated(reason + "; a new proposal commit (a new case) is required")


def _refresh(rundir, case, state, *, persist=True):
    """Re-verify the action bytes and every anchor, drop reviews whose Merkle edge
    digest changed (every ancestor of a change), apply R0 triggers. Returns the changes."""
    if state["invalidated"]:
        raise CaseInvalidated(state["invalidated"] + "; a new proposal commit (a new case) is required")
    for pin in case["decision_point"]["action"]["pins"]:
        if not _pin_ok(rundir, pin):
            reason = f"the action bytes changed after the proposal commit ({pin['path']})"
            if persist:
                _invalidate(rundir, case, state, reason)
            raise CaseInvalidated(reason + "; a new proposal commit (a new case) is required")
    context = _context(rundir, case, state)
    statuses = anchor_check.verify_all(case["anchors"], rundir, context=context)
    changes = []
    for anchor in case["anchors"]:
        anchor["verified"] = statuses[anchor["id"]][0]
    status = {aid: s for aid, (s, _, _) in statuses.items()}
    if status != state["anchor_status"]:
        changes.append("anchor_status")
    state["anchor_status"] = status
    state["anchor_reasons"] = {aid: r for aid, (_, r, _) in statuses.items() if r}
    state["observed"] = {aid: o for aid, (s, _, o) in statuses.items() if s == "external"}
    digests = dc.merkle(case)["edges"]
    for edge in case["edges"]:
        if edge["review"] is not None and edge["review"]["edge_sha256"] != digests[edge["id"]]:
            edge["review"] = None
            changes.append("review_dropped:" + edge["id"])
    unknowns = _open_unknowns(rundir, case, context)
    if unknowns != state["open_unknowns"]:
        state["open_unknowns"] = unknowns
        changes.append("open_unknowns")
    tests = _finding_tests(rundir, case, state, context)
    if tests != state.get("finding_tests", {}):
        state["finding_tests"] = tests
        changes.append("finding_tests")
    if case["risk"]["class"] == "R0":
        tolerance = anchor_check.policy()["conflict_default_relative_tolerance"]
        triggers = sorted(set(anchor_check.conflicting_nodes(case, status, tolerance, state["observed"]))
                          | {n["id"] for n in case["nodes"] if n["confidence"] == "low"})
        if triggers:
            case["risk"]["class"] = "R1"
            case["risk"]["computed_factors"]["trigger_at_r0"] = triggers
            changes.append("class_raised")
    closure = _closure(case, state)
    if closure != state.get("support_closure"):
        state["support_closure"] = closure
        changes.append("support_closure")
    return changes


def _extra(nodes, node_id, edge, conflicts, disagreement):
    count = (nodes[node_id]["confidence"] == "low") + (node_id in conflicts)
    if edge is not None:
        count += edge["id"] in disagreement
        if edge["review"] is not None:
            review = edge["review"]
            count += (review["entailment"] == "partial") + (review["grounding"] == "needs_depth") \
                + (review["relevance"] == "weak")
    return count


def _frontier(case, state, cls):
    """Open leaves the proposer must answer, branches held unresolved, edges awaiting review."""
    pol = anchor_check.policy()
    rules = pol["classes"][cls]
    nodes = _nodes(case)
    status = state["anchor_status"]
    conflicts = set(anchor_check.conflicting_nodes(case, status, pol["conflict_default_relative_tolerance"],
                                                   state["observed"]))
    disagreement = set(state["disagreement"])
    blocked = {e["id"] for e in case["edges"] if _blocked(e)} | set(state["blocking"])
    unknown = set(state["open_unknowns"])
    anchors = {a["id"]: a for a in case["anchors"]}
    open_leaves, unresolved, waiting, closed = {}, {}, set(), []
    for ids, edges in anchor_check.material_paths(case):
        leaf, depth = ids[-1], len(edges)
        if any(e["id"] in blocked for e in edges):
            continue
        if cls != "R0" and any(e["review"] is None for e in edges):
            waiting.update(e["id"] for e in edges if e["review"] is None)
            continue
        extras = _extra(nodes, ROOT, None, conflicts, disagreement) + sum(
            _extra(nodes, n, e, conflicts, disagreement) for n, e in zip(ids[1:], edges))
        required = rules["min_depth"] + (0 if cls == "R0" else extras)
        external = [a for a in nodes[leaf]["anchors"] if status.get(a) == "external"]
        invariant_only = bool(external) and cls in ("R0", "R1") and all(anchors[a]["kind"] == "invariant" for a in external)
        tool_ok = not rules["require_tool_anchor"] or any(
            status.get(a) == "external" and anchors[a]["kind"] in anchor_check.TOOL_KINDS
            for n in ids for a in nodes[n]["anchors"])
        generated_only = [e["id"] for e in edges if e["review"] is not None and e["review"]["grounding"] == "generated_only"]
        held = [n for n in ids if n in unknown]
        if held:
            unresolved[leaf] = {"node_id": leaf, "path": ids, "reason": f"open unknowns on {', '.join(held)} await "
                                "their evidence work items", "unknown": True}
            continue
        grounded = external and not invariant_only and not generated_only
        if grounded and depth >= required and tool_ok:
            closed.append(ids)
            continue
        reason = ("needs a first supporting claim" if not edges else
                  f"edge {generated_only[0]} was judged generated_only" if generated_only else
                  "an invariant alone cannot ground a leaf at this class" if invariant_only else
                  "needs an externally verified anchor" if not external else
                  "needs a tool-output or measurement anchor on this branch" if not tool_ok else
                  f"needs support to depth {required} (now {depth})")
        if depth >= rules["max_depth"]:
            unresolved[leaf] = {"node_id": leaf, "path": ids, "reason": reason + f"; the class maximum depth {rules['max_depth']} is reached"}
            if not grounded:  # Evidence gathered later can still be attached here.
                open_leaves.setdefault(leaf, {"node_id": leaf, "path": ids, "reason": reason + " (anchors only: the "
                                              "maximum depth is reached)", "anchor_only": True})
        else:
            open_leaves.setdefault(leaf, {"node_id": leaf, "path": ids, "reason": reason})
    return open_leaves, unresolved, waiting, closed


def _has_alternative(case):
    return any(e["parent"] == ROOT and e["relation"] == "chosen_over" for e in case["edges"])


def _findings(case):
    return {f["id"]: f for f in (case["critique"] or {"findings": []})["findings"]}


def _edge_findings(case, state):
    edges = {e["id"] for e in case["edges"]}
    return {EDGE_FINDING + eid: {"id": EDGE_FINDING + eid, "code": row["code"], "targets": [eid], "materiality": "A"}
            for eid, row in state["blocking"].items() if eid in edges}


def _pending_findings(case, state):
    """Blocking critique findings (``finding_status``) not yet addressed (or reopened by the verifier),
    and blocking edge verdicts, which persist until a revision addressing them changes the edge's support."""
    addressed = {f for r in case["revisions"] for f in r["addresses"]}
    rows = [f for f in _findings(case).values() if finding_status(case, state, f) == "blocking"
            and (f["id"] not in addressed or f["id"] in state["reopened"])]
    return rows + list(_edge_findings(case, state).values())


def _finding_nodes(case, finding):
    nodes, edges = _nodes(case), {e["id"]: e for e in case["edges"]}
    targets = set()
    for target in finding["targets"]:
        if target in nodes:
            targets.add(target)
        elif target in edges:
            targets.add(edges[target]["child"])
    return targets


def _challenge(case, kind, target, text, reason, extra=None):
    digest = dc.merkle(case)["nodes"].get(target, target)
    return {"id": "c-" + dc.jdigest({"case": case["case_id"], "kind": kind, "target": target, "at": digest,
                                     "extra": extra})[:12],
            "kind": kind, "target": target, "text": text, "reason": reason,
            "round": len(case["revisions"]), **({"finding_id": extra} if extra else {})}


def _challenges(case, state):
    cls = case["risk"]["class"]
    rules = anchor_check.policy()["classes"][cls]
    nodes = _nodes(case)
    open_leaves, _, _, _ = _frontier(case, state, cls)
    out = []
    for leaf in open_leaves.values():
        node = nodes[leaf["node_id"]]
        if node["id"] == ROOT:
            out.append(_challenge(case, "why_action", ROOT, f"Why should this action be taken: {node['assertion']}",
                                  leaf["reason"]))
        else:
            out.append(_challenge(case, "why_believe", node["id"], f"Why should this be believed: {node['assertion']}",
                                  leaf["reason"]) | ({"anchor_only": True} if leaf.get("anchor_only") else {}))
    if rules["require_alternative"] and not _has_alternative(case) and any(e["parent"] == ROOT for e in case["edges"]):
        out.append(_challenge(case, "why_over_alternative", ROOT,
                              "Why this action over the strongest alternative? Add that alternative and why it was not chosen.",
                              "this class requires one alternative node"))
    if len(case["revisions"]) < rules["revision_rounds"]:
        for finding in _pending_findings(case, state):
            out.append(_challenge(case, "address_finding", ",".join(finding["targets"]),
                                  f"Address finding {finding['id']} ({finding['code']}) on {', '.join(finding['targets'])}",
                                  "an A or B finding needs a revision of the targeted nodes or edges", finding["id"]))
    return out


def _verify_digest(case, state):
    """What a verification binds: the whole case's Merkle root, findings and their status
    (basis and requested tests), revisions, blocking edges and every edge verdict."""
    return dc.jdigest({"root": dc.merkle(case)["nodes"][ROOT], "findings": (case["critique"] or {}).get("findings"),
                       "revisions": case["revisions"], "blocking": sorted(state["blocking"]),
                       "verdicts": sorted([e["id"], dc.jdigest(e["review"])] for e in case["edges"] if e["review"]),
                       "basis": state.get("finding_basis", {}), "tests": state.get("finding_tests", {})})


def _critic_digest(case):
    """What a critique binds: the case's Merkle root and its revision count (any growth reruns it)."""
    return dc.jdigest({"root": dc.merkle(case)["nodes"][ROOT], "revisions": len(case["revisions"])})


def _critic_fresh(case, state):
    return case["critique"] is not None and state["critic_revision"] == len(case["revisions"]) \
        and state.get("critic_digest") == _critic_digest(case)


def _needs_review(case, state):
    return [e for e in case["edges"] if e["review"] is None and e["id"] not in state["blocking"]]


def _pending_roles(case, state, challenges):
    if state["invalidated"] or state["budget_exhausted"]:
        return []
    rules = anchor_check.policy()["classes"][case["risk"]["class"]]
    if "edge_reviewer" in rules["roles"] and _needs_review(case, state):
        return ["edge_reviewer"]
    if challenges:
        return []
    if "critic" in rules["roles"] and not _critic_fresh(case, state):
        return ["critic"]
    if "verifier" in rules["roles"] and case["critique"] is not None \
            and state["verified_digest"] != _verify_digest(case, state):
        return ["verifier"]
    return []


# ---------------------------------------------------------------- proposer side

def next_challenges(rundir, case_id):
    """The code-generated "why" challenges the proposer must answer now."""
    with _lock(rundir, case_id):
        case, state, _ = _load(rundir, case_id)
        if _refresh(rundir, case, state):
            _commit(rundir, case, state, "refreshed")
        return _challenges(case, state)


def _new_anchor(case, node_id, spec):
    if type(spec) is not dict or set(spec) - ANCHOR_FIELDS or not {"kind", "binding"} <= set(spec):
        raise ValueError(f"an anchor gives {sorted(ANCHOR_FIELDS)}; 'verified' is written only by code")
    taken = {a["id"] for a in case["anchors"]}
    index = 1
    while f"{node_id}.a{index}" in taken:
        index += 1
    anchor = {"id": f"{node_id}.a{index}", "kind": spec["kind"], "binding": spec["binding"],
              "locator": spec.get("locator", ""), "value": spec.get("value"), "quantity": spec.get("quantity"),
              "verified": None}
    case["anchors"].append(anchor)
    return anchor["id"]


def _new_node(case, spec, author, round_):
    if type(spec) is not dict or set(spec) - NODE_FIELDS or not {"id", "assertion", "rationale"} <= set(spec):
        raise ValueError(f"a node gives id, assertion and rationale (optional: {sorted(NODE_FIELDS)})")
    if spec["id"] in _nodes(case) or spec["id"] == ROOT:
        raise ValueError(f"node id {spec['id']} already exists; accepted nodes are not rewritten")
    kind = spec.get("kind", "claim")
    if kind not in ("claim", "assumption", "alternative"):
        raise ValueError("an answer adds claim, assumption or alternative nodes")
    node = {"id": spec["id"], "kind": kind, "assertion": spec["assertion"], "rationale": spec["rationale"],
            "material": spec.get("material", kind != "alternative"), "round": round_, "author": author,
            "confidence": spec.get("confidence"), "anchors": [], "assumptions": list(spec.get("assumptions", [])),
            "unknowns": list(spec.get("unknowns", [])), "recommends_choice": bool(spec.get("recommends_choice", False))}
    case["nodes"].append(node)
    for anchor in spec.get("anchors", []):
        node["anchors"].append(_new_anchor(case, node["id"], anchor))
    return node


def _edge_question(parent, child, relation):
    if relation == "chosen_over":
        return f"Why was this action chosen over: {child['assertion']}?"
    verb = "rule out" if relation == "rules_out" else "establish"
    return f"Why does '{child['assertion']}' {verb} '{parent['assertion']}'?"


def _prune(case):
    reachable, stack = set(), [ROOT]
    children = {}
    for edge in case["edges"]:
        children.setdefault(edge["parent"], []).append(edge["child"])
    while stack:
        node_id = stack.pop()
        if node_id not in reachable:
            reachable.add(node_id)
            stack.extend(children.get(node_id, []))
    case["nodes"] = [n for n in case["nodes"] if n["id"] in reachable]
    case["edges"] = [e for e in case["edges"] if e["parent"] in reachable and e["child"] in reachable]
    used = {a for n in case["nodes"] for a in n["anchors"]}
    case["anchors"] = [a for a in case["anchors"] if a["id"] in used]


def _content(node, anchors):
    return {"assertion": node["assertion"], "rationale": node["rationale"], "confidence": node["confidence"],
            "anchors": [{k: anchors[a][k] for k in ("kind", "binding", "locator")} for a in node["anchors"]]}


def answer(rundir, case_id, answers, *, expected_case_sha256=None):
    """Apply the proposer's answers: new children and anchors for open challenges, or a revision
    of the nodes and edges that a pending finding targets. Accepted nodes are never rewritten
    except by a revision, which records before/after content; confidence may only decrease."""
    if not isinstance(answers, list) or not answers:
        raise ValueError("answers must be a nonempty list")
    with _lock(rundir, case_id):
        case, state, _ = _load(rundir, case_id)
        if expected_case_sha256 is not None and dc.jdigest(case) != expected_case_sha256:
            raise ValueError("proposer answers belong to a stale case")
        _refresh(rundir, case, state)
        author = state["proposer"]
        challenges = {c["id"]: c for c in _challenges(case, state)}
        pending = {f["id"]: f for f in _pending_findings(case, state)}
        rules = anchor_check.policy()["classes"][case["risk"]["class"]]
        work = deepcopy(case)
        revising = any(isinstance(a, dict) and (a.get("op") in ("revise_node", "remove_edge") or a.get("addresses"))
                       for a in answers)
        round_ = len(work["revisions"]) + 1 if revising else len(work["revisions"])
        addresses, changed_nodes, changed_edges, new_nodes, diff = set(), set(), set(), set(), {}
        before_anchors = {a["id"]: a for a in case["anchors"]}

        def revision_scope(op):
            ids = op.get("addresses")
            if not ids or any(i not in pending for i in ids):
                raise ValueError("a revision addresses pending finding ids")
            if len(case["revisions"]) >= rules["revision_rounds"]:
                _write_receipt(rundir, case, state, "escalate", 0,
                               reason="the revision budget was spent with findings " + ", ".join(sorted(pending)))
                raise ValueError("the revision budget of this class is spent; the action is escalated")
            addresses.update(ids)
            scope = set().union(*(_finding_nodes(work, pending[i]) for i in ids)) | new_nodes
            return scope | {e["parent"] for e in work["edges"] if e["id"] in
                            {t for i in ids for t in pending[i]["targets"]}}

        def remember(node_id):
            original = _nodes(case).get(node_id)
            if original is not None and node_id not in diff:
                diff[node_id] = _content(original, before_anchors)

        for op in answers:
            kind = op.get("op") if isinstance(op, dict) else None
            if kind == "add_child":
                parent = op.get("parent")
                if op.get("addresses"):
                    if parent not in revision_scope(op):
                        raise ValueError("a revision adds children only under the targeted nodes")
                else:
                    challenge = challenges.get(op.get("challenge_id"))
                    if challenge is None or challenge["kind"] == "address_finding" or challenge["target"] != parent:
                        raise ValueError("add_child answers a current challenge on its parent")
                    if challenge.get("anchor_only"):
                        raise ValueError("this leaf is at the maximum depth; attach anchors instead")
                    if challenge["kind"] == "why_over_alternative" and op["node"].get("kind") != "alternative":
                        raise ValueError("the alternative challenge is answered with an alternative node")
                if parent not in _nodes(work):
                    raise ValueError("unknown parent node")
                depth = max((ids.index(parent) for ids, _ in anchor_check.material_paths(work) if parent in ids), default=0)
                if op["node"].get("kind") != "alternative" and depth + 1 > rules["max_depth"]:
                    raise ValueError(f"the class maximum depth {rules['max_depth']} is reached; attach anchors instead")
                node = _new_node(work, op.get("node"), author, round_)
                relation = "chosen_over" if node["kind"] == "alternative" else op.get("relation", "supports")
                if relation not in ("supports", "rules_out", "chosen_over"):
                    raise ValueError("unknown relation")
                parent_node = _nodes(work)[parent]
                work["edges"].append({"id": f"{parent}->{node['id']}", "parent": parent, "child": node["id"],
                                      "round": round_, "challenge": _edge_question(parent_node, node, relation),
                                      "relation": relation, "author": author, "review": None})
                new_nodes.add(node["id"])
                if op.get("addresses"):
                    remember(parent)
                    changed_nodes.add(node["id"]); changed_edges.add(f"{parent}->{node['id']}")
            elif kind == "attach_anchor":
                node_id = op.get("node_id")
                if op.get("addresses"):
                    if node_id not in revision_scope(op):
                        raise ValueError("a revision attaches anchors only to targeted nodes")
                    remember(node_id)
                    changed_nodes.add(node_id)
                else:
                    challenge = challenges.get(op.get("challenge_id"))
                    if challenge is None or challenge["kind"] != "why_believe" or challenge["target"] != node_id:
                        raise ValueError("attach_anchor answers a current challenge on an open leaf")
                _nodes(work)[node_id]["anchors"].append(_new_anchor(work, node_id, op.get("anchor")))
            elif kind == "revise_node":
                node_id = op.get("node_id")
                if node_id == ROOT:
                    _invalidate(rundir, case, state, "the proposer tried to rewrite the committed action")
                if node_id not in revision_scope(op):
                    raise ValueError("only nodes targeted by a pending finding are revised")
                fields = op.get("fields")
                if type(fields) is not dict or not fields or set(fields) - {"assertion", "rationale", "confidence", "anchors"}:
                    raise ValueError("revise_node changes assertion, rationale, confidence or anchors")
                node = _nodes(work)[node_id]
                remember(node_id)
                if "confidence" in fields:
                    if fields["confidence"] not in dc.CONFIDENCE or \
                            CONFIDENCE_LEVEL[fields["confidence"]] > CONFIDENCE_LEVEL[node["confidence"]]:
                        raise ValueError("confidence may only decrease")
                for key in ("assertion", "rationale", "confidence"):
                    if key in fields:
                        node[key] = fields[key]
                if "assertion" in fields:  # Questions about a revised claim are asked afresh.
                    present = _nodes(work)
                    for edge in work["edges"]:
                        if node_id in (edge["parent"], edge["child"]):
                            edge["challenge"] = _edge_question(present[edge["parent"]], present[edge["child"]],
                                                               edge["relation"])
                if "anchors" in fields:
                    node["anchors"] = [_new_anchor(work, node_id, spec) for spec in fields["anchors"]]
                node["round"] = round_
                changed_nodes.add(node_id)
            elif kind == "remove_edge":
                edges = {e["id"]: e for e in work["edges"]}
                edge = edges.get(op.get("edge_id"))
                if edge is None or (edge["child"] not in revision_scope(op) and edge["id"] not in
                                    {t for i in op["addresses"] for t in pending[i]["targets"]}):
                    raise ValueError("only targeted edges are removed")
                remember(edge["parent"])
                work["edges"].remove(edge)
                changed_nodes.add(edge["parent"]); changed_edges.add(edge["id"])
            else:
                raise ValueError("answer op must be add_child, attach_anchor, revise_node or remove_edge")
        _prune(work)
        if addresses or changed_nodes:
            if not addresses:
                raise ValueError("a revision names the findings it addresses")
            after_anchors = {a["id"]: a for a in work["anchors"]}
            present = _nodes(work)
            rows = [{"id": n, "before": before, "after": _content(present[n], after_anchors) if n in present else None}
                    for n, before in sorted(diff.items())]
            work["revisions"].append({"round": round_, "addresses": sorted(addresses), "changed_nodes": sorted(changed_nodes),
                                      "changed_edges": sorted(changed_edges), "diff": rows})
            state["reopened"] = [f for f in state["reopened"] if f not in addresses]
        dc.validate_case_v2(work)
        _refresh(rundir, work, state)
        digests = dc.merkle(work)["edges"]
        for finding_id in sorted(a for a in addresses if a.startswith(EDGE_FINDING)):
            edge_id = finding_id[len(EDGE_FINDING):]
            if edge_id in digests and digests[edge_id] == state["blocking"][edge_id]["edge_sha256"]:
                raise ValueError(f"a revision addressing {finding_id} must change the support of that edge")
            del state["blocking"][edge_id]
        for node in work["nodes"]:
            if node["id"] in new_nodes:
                for unknown in node["unknowns"]:
                    evidence_queue.enqueue(rundir, case_id, source="node_unknown", target=node["id"],
                                           request=_unknown_request(unknown), round_=len(work["revisions"]))
        state["open_unknowns"] = _open_unknowns(rundir, work, _context(rundir, work, state))
        state["support_closure"] = _closure(work, state)
        _commit(rundir, work, state, "answer", {"answers_sha256": dc.jdigest(answers),
                                                "revision": work["revisions"][-1] if addresses else None})
        return _challenges(work, state)


# ---------------------------------------------------------------- role dispatch

OUTPUT_SCHEMAS = {
    "edge_reviewer": {"type": "object", "additionalProperties": False, "required": ["reviews"], "properties": {
        "reviews": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["edge_id", "entailment", "relevance", "grounding", "code", "reason", "request"],
            "properties": {"edge_id": {"type": "string"}, "entailment": {"enum": list(dc.ENTAILMENT)},
                           "relevance": {"enum": list(dc.RELEVANCE)}, "grounding": {"enum": list(dc.GROUNDING)},
                           "code": {"enum": list(dc.CRITIQUE_CODES)}, "reason": {"type": "string", "maxLength": dc.MAX_REASON},
                           "request": {"anyOf": [{"type": "null"}, {"type": "object", "additionalProperties": False,
                                       "required": ["kind", "description"],
                                       "properties": {"kind": {"enum": list(dc.REQUEST_KINDS)},
                                                      "description": {"type": "string",
                                                                      "maxLength": dc.MAX_DESCRIPTION}}}]}}}}}},
    "critic": {"type": "object", "additionalProperties": False, "required": ["findings"], "properties": {
        "findings": {"type": "array", "items": {"type": "object", "required": sorted(dc.FINDING_KEYS),
            "properties": {"id": {"type": "string"}, "code": {"enum": list(dc.CRITIQUE_CODES)},
                           "targets": {"type": "array", "items": {"type": "string"}},
                           "materiality": {"enum": list(dc.MATERIALITY)},
                           "evidence_class": {"enum": list(dc.EVIDENCE_CLASSES)},
                           "evidence_locators": {"type": "array", "items": {"type": "string"}},
                           "request": {"anyOf": [{"type": "null"}, {"type": "object", "additionalProperties": False,
                                       "required": ["kind", "description"],
                                       "properties": {"kind": {"enum": list(dc.REQUEST_KINDS)},
                                                      "description": {"type": "string",
                                                                      "maxLength": dc.MAX_DESCRIPTION},
                                                      "max_broker_calls": {"type": "integer", "minimum": 0}}}]},
                           "alternative": {"type": "string", "maxLength": dc.MAX_DESCRIPTION}}}},
        "withdrawn": {"type": "array", "items": {"type": "string"}}}},
    "verifier": {"type": "object", "additionalProperties": False, "required": ["per_finding", "outcome"], "properties": {
        "per_finding": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["finding_id", "resolved", "reason"],
            "properties": {"finding_id": {"type": "string"}, "resolved": {"enum": list(dc.RESOLVED)},
                           "reason": {"type": "string", "maxLength": dc.MAX_REASON}}}},
        "outcome": {"enum": list(dc.OUTCOMES)}}},
}


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


class AgentHostDispatcher:
    """Run each role call as one standard ``model`` node of ``agent_graph`` on a production host.

    Nodes use the registered roles ``rdj_edge_reviewer``, ``rdj_critic`` and
    ``rdj_verifier``. The edge reviewer receives the payload as a pinned input; the
    critic and verifier are blind roles and receive it only as a digest-bound role
    packet, so the agent layer's packet rule and per-role audits apply. The loop reads
    identity from the host-written model receipt, never from this object.
    """

    def __init__(self, host, *, model, reasoning_effort="medium", max_output_tokens=8192, max_wall_seconds=3600):
        self.host = host
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.budget = {"max_nodes": 1, "max_calls": 1, "max_output_tokens": max_output_tokens,
                       "max_wall_seconds": max_wall_seconds, "max_reworks": 0}

    @staticmethod
    def packet(directory, agent_role, payload_file):
        """A role packet in the review-context layout holding exactly the RDJ projection."""
        from . import execution
        raw = payload_file.read_bytes()
        (directory / "artifacts").mkdir(parents=True)
        (directory / "artifacts" / "rdj-payload.json").write_bytes(raw)
        sha = anchor_check.sha256_file(payload_file)
        manifest = {"schema_version": 1, "kind": "rdj_role_packet_v1", "role": agent_role,
                    "artifacts": [{"id": "rdj-payload", "path": "artifacts/rdj-payload.json", "sha256": sha,
                                   "source_path": str(payload_file), "source_sha256": sha}],
                    "omissions": []}
        manifest["sha256"] = execution.digest(manifest)
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return {"path": str(directory), "manifest_sha256": manifest["sha256"]}

    def dispatch(self, rundir, request):
        from . import agent_graph
        root = Path(rundir) / request["graph_root"]
        work = root.parent / (root.name + ".inputs")
        work.mkdir(parents=True)
        payload_file = work / "payload.json"
        payload_file.write_bytes(_canonical_bytes(request["payload"]))
        agent_role = request["agent_role"]
        blind = request["role"] in ("critic", "verifier")
        packet = self.packet(work / "packet", agent_role, payload_file) if blind else None
        inputs = [] if blind else [{"id": "rdj-payload", "path": str(payload_file),
                                    "sha256": request["payload_sha256"]}]
        parameters = {"instructions": request["payload"]["instructions"], "model": self.model,
                      "reasoning_effort": self.reasoning_effort, "max_output_tokens": self.budget["max_output_tokens"],
                      "output_schema": OUTPUT_SCHEMAS[request["role"]]}
        spec = {"schema_version": 1, "graph_id": f"rdj-{request['slot']:04d}-{request['role'].replace('_', '-')}",
                "budget": self.budget,
                "nodes": [{"id": "rdj", "kind": "model", "role": agent_role, "depends_on": [], "inputs": inputs,
                           "packet": packet, "action": "model", "parameters": parameters, "max_attempts": 1}]}
        agent_graph.create(root, spec)
        state = agent_graph.execute(root, self.host)
        if state["nodes"]["rdj"]["status"] != "completed":
            raise ValueError(f"{request['role']} call did not complete: {state['nodes']['rdj']['error']}")
        model = agent_graph.role_receipt(root, "rdj", expected_subject_sha256=request["payload_sha256"],
                                         require_exact_subject=True, allowed_roles={agent_role})
        custody.register_graph_receipt(rundir, request["graph_root"], model["receipt_sha256"], model["host_sha256"])
        return {"kind": "agent_graph", "root": request["graph_root"], "node_id": "rdj"}


def _resolve(rundir, request, ref):
    """Output, session and model family of one role call, read from its host-written receipt."""
    role, agent_role = request["role"], request["agent_role"]
    if type(ref) is not dict or ref.get("kind") not in ("worker_receipt", "agent_graph"):
        raise ValueError("a role call returns a receipt reference (worker_receipt or agent_graph), never a session "
                         "the model states")
    if ref["kind"] == "worker_receipt":
        path, rel = anchor_check.inside(rundir, ref.get("path"))
        sha = anchor_check.sha256_file(path)
        registration = custody.worker_row(rundir, rel, sha)
        if registration is None:
            raise ValueError("the worker receipt is not registered by the worker dispatcher")
        receipt = read_json(path)
        if receipt.get("schema_version") not in (1, 2, 3) or receipt.get("kind") != "agent-worker-receipt" \
                or receipt.get("status") != "ok" or (receipt.get("role") or {}).get("id") != agent_role:
            raise ValueError("the worker receipt is not a successful receipt for this role")
        if receipt.get("rdj") != {"case_id": request["case_id"], "slot": request["slot"],
                                  "payload_sha256": request["payload_sha256"]}:
            raise ValueError("the worker receipt belongs to a different role call")
        final = receipt.get("final_record") or {}
        try:
            final_path, _ = anchor_check.inside(path.parent, str(final.get("path")))
        except anchor_check.AnchorError as exc:
            raise ValueError(f"the worker's final record is not inside its receipt directory: {exc}") from None
        if not final.get("valid") or anchor_check.sha256_file(final_path) != final.get("sha256"):
            raise ValueError("the worker's final record differs from its receipt")
        output = read_json(final_path)
        # The label comes from the dispatcher's registration, bounded by the observed execution mode;
        # the receipt's own ``attestation`` field is a self-claim and is never read. A receipt
        # written before the mode was recorded takes the mode of its dispatcher-written transport.
        from . import agent_worker, review_points
        verified = registration.get("verified_label")
        attested = "self_attested"
        if verified is not None:
            mode = receipt.get("execution_mode") or agent_worker.execution_mode(receipt.get("transport"))
            attested = dc.label_for(mode, verified)
            if dc.ATTESTATION_RANK[attested] > dc.ATTESTATION_RANK[verified]:
                attested = verified
        # The identity is the actor the dispatcher assigned and registered. A receipt that only
        # states an actor, or states none, has no assigned actor: it is one unattested call.
        assigned = review_points.registered_actor(receipt, registration)
        if assigned is None:
            attested = "self_attested"
        session = {"actor_id": assigned["actor_id"] if assigned else "unassigned:" + sha,
                   "session_receipt": f"{receipt['transport']['id']}:{receipt['session_id']}",
                   "attestation": attested}
        family = (receipt.get("model") or {}).get("family")
    else:
        from . import agent_graph
        if ref.get("root") != request["graph_root"]:
            raise ValueError("the model receipt is not at the reserved graph root")
        model = agent_graph.role_receipt(Path(rundir) / ref["root"], ref.get("node_id"),
                                         expected_subject_sha256=request["payload_sha256"],
                                         require_exact_subject=True, allowed_roles={agent_role})
        if not custody.graph_receipt_registered(rundir, ref["root"], model["receipt_sha256"], model["host_sha256"]):
            raise ValueError("the model receipt was not registered by the RDJ dispatcher")
        transport, isolation = model["transport"], model.get("isolation") or {}
        output = model["public_value"]
        # Transport attestation needs a host the operator registered and a fresh, separated request;
        # an unregistered or in-process host is self-attested whatever its result says.
        separated = isolation.get("fresh_request") is True and isolation.get("parent_transcript_supplied") is False
        attested = dc.label_for(model["execution_observation"], model.get("attestation")) \
            if custody.host_registered(rundir, model["host_sha256"]) and separated else "self_attested"
        # The identity is built from what the dispatcher owns: the adapter, the requested model,
        # the request it issued and the graph node. An actor a host response states is never read.
        session = {"actor_id": custody.actor_id(str(transport.get("adapter") or "host"),
                                                str(transport.get("requested_model") or "unspecified"),
                                                str(transport["request_id"]), f"{ref['root']}#{ref.get('node_id')}"),
                   "session_receipt": f"{ref['root']}#{model['receipt_sha256']}", "attestation": attested}
        family = transport.get("family")  # an adapter name is not a model family
    return output, dc.actor(session, role + " session"), family


def _anchors_shown(case, state, node):
    anchors = {a["id"]: a for a in case["anchors"]}
    return [anchor_check.describe(anchors[a], state["observed"].get(a)) for a in node["anchors"]]


def _projection(case, state):
    """The case as the critic and verifier see it: structure, anchors and verdicts; reviewer reasons withheld."""
    nodes = [{k: n[k] for k in ("id", "kind", "assertion", "rationale", "material", "confidence", "recommends_choice",
                                "assumptions", "unknowns")} | {"anchors": _anchors_shown(case, state, n)}
             for n in case["nodes"]]
    edges = [{k: e[k] for k in ("id", "parent", "child", "relation", "challenge")}
             | {"review": None if e["review"] is None else
                {k: e["review"][k] for k in ("entailment", "relevance", "grounding", "code")}} for e in case["edges"]]
    return {"case_id": case["case_id"], "decision_point": case["decision_point"], "class": case["risk"]["class"],
            "nodes": nodes, "edges": edges}


def _payload(role, case, state):
    gate = case["decision_point"]["gate"]
    if role == "edge_reviewer":
        nodes = _nodes(case)
        edges = _needs_review(case, state)
        return {"role": "rdj-edge-reviewer", "case_id": case["case_id"], "class": case["risk"]["class"],
                "instructions": "Judge each hop alone: does the child establish (or rule out) the parent, is it "
                                "relevant, and is it grounded in its verified anchors (the values shown were read "
                                "from the verified bytes)? The code is no_issue exactly when the hop holds, is "
                                "relevant and is anchored. Use unmarked_choice when the child recommends an analysis "
                                "choice. Return one review per edge.",
                "edges": [{"edge_id": e["id"], "challenge": e["challenge"], "relation": e["relation"],
                           "parent": {k: nodes[e["parent"]][k] for k in ("id", "kind", "assertion")},
                           "child": {k: nodes[e["child"]][k] for k in ("id", "kind", "assertion", "rationale", "confidence",
                                                                        "assumptions", "unknowns")}
                           | {"anchors": _anchors_shown(case, state, nodes[e["child"]])}} for e in edges],
                "output_schema": OUTPUT_SCHEMAS["edge_reviewer"]}
    if role == "critic":
        since = state["critic_revision"] or 0
        return {"role": CRITIC_CARD.get(gate, "decision-critic"), "case": _projection(case, state),
                "prior_findings": [{k: f[k] for k in ("id", "code", "targets", "materiality")}
                                   for f in _findings(case).values()],
                "diff": case["revisions"][since:] if state["critic_revision"] is not None else [],
                "instructions": "Return new findings only, each with a code from the closed list and new ids. On a "
                                "revision, judge the diff. Do not write plans. Give each finding its evidence "
                                "class: new_receipt (name the stage receipt of a test you ran), code_check (name "
                                "the case elements or run files code can check), cited, or opinion. Only "
                                "new_receipt and code_check findings, or findings that request a discriminating "
                                "test, can hold the decision; for a request, ask for the cheapest test that could "
                                "invalidate the claim and bound its max_broker_calls.",
                "output_schema": OUTPUT_SCHEMAS["critic"]}
    return {"role": VERIFIER_CARD.get(gate, "decision-verifier"), "case": _projection(case, state),
            "findings": [{**f, "holds": finding_status(case, state, f), "test": state.get("finding_tests", {}).get(
                f["id"])} for f in _findings(case).values()],
            "edge_findings": list(_edge_findings(case, state).values()), "revisions": case["revisions"],
            "instructions": "For each finding say whether a revision resolved it (yes only when a revision addressed "
                            "it; no; or new_issue tied to a revision), using the before and after content, then "
                            "authorize, escalate or gather_evidence.",
            "output_schema": OUTPUT_SCHEMAS["verifier"]}


def _same(a, b):
    return a["actor_id"] == b["actor_id"] or (a["session_receipt"] is not None
                                              and a["session_receipt"] == b["session_receipt"])


def _refuse_if_same(session, others, message):
    if any(_same(session, other) for other in others):
        raise IndependenceError(message)


def _mark_choice(case, state, code, targets):
    if code != "unmarked_choice":
        return
    edges = {e["id"]: e for e in case["edges"]}
    for target in targets:
        node = edges[target]["child"] if target in edges else target
        if node not in state["choice_marked"]:
            state["choice_marked"].append(node)


def _record_edge_reviews(rundir, case, state, output, session, requested):
    if type(output) is not dict or set(output) != {"reviews"} or not isinstance(output["reviews"], list):
        raise ValueError("edge reviewer output is exactly {reviews: [...]}")
    judges = state["critic_sessions"] + ([case["verification"]["reviewer"]] if case["verification"] else [])
    _refuse_if_same(session, state["authors"] + judges,
                    "an edge reviewer must differ from every author, the critic and the verifier")
    edges = {e["id"]: e for e in case["edges"]}
    digests = dc.merkle(case)["edges"]
    rows = {}
    for row in output["reviews"]:
        dc.keys(row, {"edge_id", "entailment", "relevance", "grounding", "code", "reason", "request"}, "edge review row")
        if row["edge_id"] in rows:
            raise ValueError("duplicate edge review row for one edge")
        rows[row["edge_id"]] = row
    if set(rows) != set(requested):
        raise ValueError("the edge reviewer must return exactly one review per requested edge")
    for edge_id, row in rows.items():
        edge = edges[edge_id]
        review = {"reviewer": session, "edge_sha256": digests[edge_id],
                  **{k: row[k] for k in ("entailment", "relevance", "grounding", "code", "reason", "request")}}
        dc.edge_review(review)
        edge["review"] = review
        if _blocked(edge):
            state["blocking"][edge_id] = {"edge_sha256": digests[edge_id], "code": review["code"],
                                          "reason": review["reason"]}
        _mark_choice(case, state, review["code"], [edge_id])
        if review["request"] is not None and (_blocked(edge) or review["grounding"] != "anchored"):
            evidence_queue.enqueue(rundir, case["case_id"], source="edge_review", target=edge_id,
                                   request=review["request"], round_=len(case["revisions"]))
    if session not in state["reviewer_sessions"]:
        state["reviewer_sessions"].append(session)


def _record_critique(rundir, case, state, output, session):
    if type(output) is not dict or set(output) not in ({"findings"}, {"findings", "withdrawn"}):
        raise ValueError("critic output is exactly {findings: [...]} (and optionally withdrawn: [finding ids]): "
                         "the critic cannot regenerate the plan")
    verifier_ = [case["verification"]["reviewer"]] if case["verification"] else []
    _refuse_if_same(session, state["authors"] + state["reviewer_sessions"] + verifier_,
                    "the critic must be a different session and actor from every author, edge reviewer and verifier")
    prior = list(_findings(case).values())
    if any(f.get("id") in _findings(case) for f in output["findings"] if isinstance(f, dict)):
        raise ValueError("a re-run critic adds findings with new ids")
    critique = dc.critique({"reviewer": session, "findings": prior + list(output["findings"])})
    known = {n["id"] for n in case["nodes"]} | {e["id"] for e in case["edges"]}
    if any(t not in known for f in critique["findings"][len(prior):] for t in f["targets"]):
        raise ValueError("a finding targets an unknown node or edge")
    budgets = anchor_check.policy()["budgets"]
    calls = [f["request"].get("max_broker_calls", 0) for f in critique["findings"][len(prior):] if f["request"]]
    if any(c > budgets["max_critic_broker_calls"] for c in calls) \
            or sum(calls) > budgets["max_critic_broker_calls_per_critique"]:
        raise ValueError(f"a critic request's max_broker_calls exceeds the policy bound "
                         f"({budgets['max_critic_broker_calls']} per test, "
                         f"{budgets['max_critic_broker_calls_per_critique']} per critique)")
    raised = state.setdefault("finding_raised_by", {})
    withdraw = output.get("withdrawn", [])
    if not isinstance(withdraw, list) or any(raised.get(fid) != session["session_receipt"] for fid in withdraw):
        raise ValueError("a critic may withdraw only findings its own session raised")
    state["critic_withdrawn"] = sorted(set(state.get("critic_withdrawn") or ()) | set(withdraw))
    context = _context(rundir, case, state)
    state.setdefault("finding_basis", {})
    for finding in critique["findings"][len(prior):]:
        raised[finding["id"]] = session["session_receipt"]
        state["finding_basis"][finding["id"]] = critic_basis(rundir, case, finding, context)
    case["critique"] = critique
    state["critic_revision"] = len(case["revisions"])
    state["critic_digest"] = _critic_digest(case)
    if session not in state["critic_sessions"]:
        state["critic_sessions"].append(session)
    edges = {e["id"]: e for e in case["edges"]}
    for finding in critique["findings"][len(prior):]:
        if finding["code"] in DISAGREEMENT_CODES:
            for target in finding["targets"]:
                hits = [edges[target]] if target in edges else [e for e in case["edges"] if e["child"] == target]
                state["disagreement"] += [e["id"] for e in hits if e["review"] and e["review"]["entailment"] == "holds"
                                          and e["id"] not in state["disagreement"]]
        _mark_choice(case, state, finding["code"], finding["targets"])
        if finding["request"] is not None:
            evidence_queue.enqueue(rundir, case["case_id"], source="critic_finding", target=finding["id"],
                                   request=finding["request"], round_=len(case["revisions"]))
    state["finding_tests"] = _finding_tests(rundir, case, state, context)


def _record_verification(rundir, case, state, output, session, family, families):
    if type(output) is not dict or set(output) != {"per_finding", "outcome"}:
        raise ValueError("verifier output is exactly {per_finding, outcome}")
    cls = case["risk"]["class"]
    _refuse_if_same(session, state["authors"] + state["reviewer_sessions"],
                    "the verifier must be a different session and actor from every author and edge reviewer")
    if any(_same(session, critic) for critic in state["critic_sessions"]):
        if cls == "R3":
            raise IndependenceError("refused: the critic and the verifier must be distinct sessions at R3")
        if not _human(rundir, case):
            raise IndependenceError("refused: a verifier in the critic's session is self_attested, "
                                    "which this class accepts only with a recorded human approval")
        session = {**session, "attestation": "self_attested"}
        state["self_attested_verifier"] = True
    if cls == "R3" and anchor_check.policy()["r3_distinct_family"]:
        critic_families = {families.get(c["session_receipt"]) for c in state["critic_sessions"]}
        if family is None or None in critic_families or family in critic_families:
            raise IndependenceError("refused: at R3 the verifier must come from a different model family than the critic")
    revised = {f for r in case["revisions"] for f in r["addresses"]}
    case["verification"] = dc.verification({"reviewer": session, **output}, list(_findings(case).values()), revised)
    state["verified_digest"] = _verify_digest(case, state)
    findings = _findings(case)
    state["reopened"] = [row["finding_id"] for row in output["per_finding"]
                         if row["resolved"] != "yes" and findings[row["finding_id"]]["materiality"] in BLOCKING_CRITIQUE
                         and findings[row["finding_id"]]["code"] != "no_issue"]


def _run_budget(rows, digest):
    """The run-wide and per-action call budgets over the ``roles`` ledger rows (checked under its lock)."""
    budgets = anchor_check.policy()["budgets"]
    calls = [r["record"] for r in rows]
    if len(calls) >= budgets["max_model_calls_per_run"]:
        return f"the run used its {budgets['max_model_calls_per_run']} decision-justification model calls"
    if sum(1 for c in calls if c["action_digest"] == digest) >= budgets["max_model_calls_per_action"]:
        return f"this action used its {budgets['max_model_calls_per_action']} model calls across cases"
    return None


def _budget_reason(rundir, case, state, role, payload):
    pol = anchor_check.policy()
    budgets = pol["budgets"]
    cap = pol["classes"][case["risk"]["class"]]["max_model_calls"]
    if state["usage"]["model_calls"] >= cap:
        return f"the case used {state['usage']['model_calls']} of {cap} model calls for its class"
    reason = _run_budget(custody.rows(rundir, "roles"), case["decision_point"]["action"]["digest"])
    if reason:
        return reason
    if role == "edge_reviewer":
        over = [e["edge_id"] for e in payload["edges"]
                if state["edge_reviews"].get(e["edge_id"], 0) >= budgets["max_reviews_per_edge"]]
        if over:
            return f"edge {over[0]} reached its {budgets['max_reviews_per_edge']} reviews"
    return None


def _finish_call(rundir, case_id, slot, status, detail=None, *, case=None, state=None, extra=None):
    if case is None:
        case, state, _ = _load(rundir, case_id)
    for call in state["calls"]:
        if call["slot"] == slot:
            call.update(status=status, detail=detail, **(extra or {}))
    _commit(rundir, case, state, "role_" + status, {"slot": slot, **({"detail": detail} if detail else {})})


def run_roles(rundir, case_id, dispatcher, *, max_steps=32):
    """Run pending roles through the registered RDJ substrate graph.

    The return value preserves the RDJ status API. Custody and code remain the
    source of identity, staleness, budgets and authorization.
    """
    from .graphs.rdj import run
    result = run(rundir, case_id, dispatcher, max_steps=max_steps)
    return {key: value for key, value in result.items() if key != "graph"}


# ---------------------------------------------------------------- authorization

def _attestation_summary(rundir, case, state):
    reviewers = sorted({e["review"]["reviewer"]["attestation"] for e in case["edges"] if e["review"]})
    critic = case["critique"]["reviewer"] if case["critique"] else None
    verifier = case["verification"]["reviewer"] if case["verification"] else None
    actors = [a for a in (state["proposer"], critic, verifier) if a is not None]
    sessions = [a["session_receipt"] for a in actors if a["session_receipt"] is not None]
    return {"edge_reviewers": reviewers, "critic": critic["attestation"] if critic else None,
            "verifier": verifier["attestation"] if verifier else None,
            "distinct_sessions": len(sessions) == len(set(sessions)),
            "distinct_actors": len({a["actor_id"] for a in actors}) == len(actors),
            "human_approver": _human(rundir, case)}


def _independence_basis(cls, summary):
    """What met the class's independence rule: every role transport-attested, or a human approval."""
    used = summary["edge_reviewers"] + [a for a in (summary["critic"], summary["verifier"]) if a]
    if all(a == "transport_attested" for a in used):
        return "transport_attested" if used else "no_roles"
    if summary["human_approver"]:
        return "human_approver"
    return "self_attested" if cls == "R1" else "insufficient"


def _item(code, message, target=None):
    return {"code": code, "message": message, "target": target}


def _exploratory(case, state):
    return anchor_check.exploratory_nodes(case, state["anchor_status"], state["choice_marked"])


SOFT = ("unresolved_branch", "finding_pending")


def _finding_rows(case, state):
    """``(finding, status, holding)`` for every critique finding. A blocking finding holds until the
    current verification resolves it; a pending test holds until it answers, unless a revision
    addressed the finding and the current verification resolved it."""
    addressed = {f for r in case["revisions"] for f in r["addresses"]}
    fresh = case["verification"] is not None and state["verified_digest"] == _verify_digest(case, state)
    resolved = {r["finding_id"]: r["resolved"] for r in case["verification"]["per_finding"]} if fresh else {}
    rows = []
    for finding in _findings(case).values():
        status_ = finding_status(case, state, finding)
        holding = (status_ == "blocking" and resolved.get(finding["id"]) != "yes") or (
            status_ == "pending_test" and not (finding["id"] in addressed and resolved.get(finding["id"]) == "yes"))
        rows.append((finding, status_, holding))
    return rows


def authorization_errors(rundir, case, state, *, refreshed=False):
    """Every reason code refuses authorization. Pure: reads files, writes nothing.
    ``refreshed`` says the caller re-verified this case in the same pass."""
    rundir = Path(rundir)
    case, state = deepcopy(case), deepcopy(state)
    if state["invalidated"]:
        return [_item("case_invalidated", state["invalidated"])]
    try:
        if not refreshed:
            _refresh(rundir, case, state, persist=False)
    except CaseInvalidated as exc:
        return [_item("action_changed", str(exc))]
    errors = []
    cls = case["risk"]["class"]
    pol = anchor_check.policy()
    rules = pol["classes"][cls]
    point = case["decision_point"]
    if state["budget_exhausted"]:
        errors.append(_item("budget_exhausted", f"the decision-justification budget is spent: {state['budget_reason']}"))
    escalated = _escalation_open(rundir, point["gate"], point["action"]["digest"], exclude=case["case_id"])
    if escalated is not None:
        errors.append(_item("action_escalated", f"case {escalated['record']['case_id']} escalated this action; a "
                            "recorded user decision must reopen it"))
    for aid, status_ in state["anchor_status"].items():
        if status_ == "invalid":
            errors.append(_item("anchor_invalid", f"anchor {aid} is invalid: {state['anchor_reasons'].get(aid)}", aid))
    open_leaves, unresolved, _, _ = _frontier(case, state, cls)
    nodes = _nodes(case)
    for path in anchor_check.self_grounded_paths(case, state["anchor_status"]):
        leaf = nodes[path[-1]]
        if path[-1] in unresolved and not any(state["anchor_status"].get(a) == "generated" for a in leaf["anchors"]):
            continue  # Stopped at the class maximum or held by unknowns: unresolved, reported below.
        errors.append(_item("self_grounding", "self-grounded path (no externally verified anchor at its leaf): "
                            + " -> ".join(path), path[-1]))
    for edge in case["edges"]:
        if edge["id"] in state["blocking"]:
            row = state["blocking"][edge["id"]]
            errors.append(_item("edge_blocked", f"edge {edge['id']} does not support its parent ({row['code']}): "
                                + row["reason"], edge["id"]))
        elif "edge_reviewer" in rules["roles"] and edge["review"] is None:
            errors.append(_item("edge_unreviewed", f"edge {edge['id']} has no current review", edge["id"]))
    for leaf in open_leaves.values():
        if leaf.get("anchor_only"):
            continue
        errors.append(_item("branch_open", f"branch {' -> '.join(leaf['path'])} {leaf['reason']}", leaf["node_id"]))
    for leaf in unresolved.values():
        errors.append(_item("unresolved_branch", f"branch {' -> '.join(leaf['path'])} is unresolved: {leaf['reason']}",
                            leaf["node_id"]))
    for node in case["nodes"]:
        if node["material"] and node["assumptions"]:
            errors.append(_item("assumption_open", f"claim {node['id']} carries free-text assumptions; state each as an "
                                "assumption node and ground it", node["id"]))
    if rules["require_alternative"] and not _has_alternative(case):
        errors.append(_item("alternative_missing", "this class needs one alternative node chosen against", ROOT))
    if RANK[cls] >= RANK["R2"]:
        for node_id in _exploratory(case, state):
            errors.append(_item("exploratory_choice", f"claim {node_id} recommends an analysis choice without an "
                                "authoritative-practice anchor; it stays exploratory", node_id))
    for row in _common_mode(case, state):
        errors.append(_item("common_mode_anchor", f"claims {', '.join(row['claims'])} rest only on one shared source "
                            f"{row['source'][1]}; add an independent external anchor to one of them",
                            row["claims"][0]))
    if "critic" in rules["roles"] and not _critic_fresh(case, state):
        errors.append(_item("critique_missing", "the critic has not reviewed the current case"))
    if "verifier" in rules["roles"]:
        if case["verification"] is None or state["verified_digest"] != _verify_digest(case, state):
            errors.append(_item("verification_missing", "the verifier has not ruled on the current case"))
        elif case["verification"]["outcome"] != "authorize":
            errors.append(_item("verifier_outcome", f"the verifier's outcome is {case['verification']['outcome']}"))
    for finding, status_, holding in _finding_rows(case, state):
        if holding and status_ == "blocking":
            errors.append(_item("finding_open", f"{finding['materiality']} finding {finding['id']} "
                                f"({finding['code']}) is not resolved", finding["id"]))
        elif holding:
            errors.append(_item("finding_pending", f"{finding['materiality']} finding {finding['id']} "
                                f"({finding['code']}) waits for the test it requested", finding["id"]))
    summary = _attestation_summary(rundir, case, state)
    used = summary["edge_reviewers"] + [a for a in (summary["critic"], summary["verifier"]) if a]
    if rules["independence"] == "transport_required" and any(a != "transport_attested" for a in used):
        errors.append(_item("attestation_insufficient", "this class requires transport-attested sessions for every role"))
    if rules["independence"] == "transport_or_human" and any(a != "transport_attested" for a in used) \
            and not summary["human_approver"]:
        errors.append(_item("attestation_insufficient", "self_attested roles at this class need a recorded human approval"))
    irreversible = pol["gates"][point["gate"]]["irreversible"] or point["action_kind"] in pol["irreversible_kinds"]
    if irreversible and not summary["human_approver"]:
        errors.append(_item("human_required", "an irreversible action also needs a recorded human approval of this case"))
    return errors


def _receipts(rundir):
    directory = _dir(rundir, "receipts")
    rows = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        receipt = read_json(path)
        if receipt.get("schema_version") != 1 or receipt.get("kind") != "rdj-receipt":
            raise ValueError(f"unknown decision-justification receipt: {path.name}")
        rows.append(receipt)
    return rows


def deviation_row(case, receipt):
    """The DEVIATIONS.md entry for an authorized deviation or tuning change."""
    point = case["decision_point"]
    files = ", ".join(p["path"] for p in point["action"]["pins"]) or "none"
    parts = [f"- {receipt['authorized_utc']}", f"{point['gate']} / {point['action_kind']}",
             f"decision justification {receipt['receipt_id']} ({receipt['class']})"]
    if "tuning" in point:
        tuning = point["tuning"]
        parts.append(f"tuning class: {tuning['class']}; {tuning['parameter']}: "
                     f"{json.dumps(tuning['from'])} -> {json.dumps(tuning['to'])}; {tuning['reason']}")
    parts += [point["action"]["summary"], f"files: {files}", f"action sha256 {point['action']['digest']}"]
    return " · ".join(parts) + "\n"


def _write_receipt(rundir, case, state, outcome, unresolved, *, reason=None):
    """Commit the case, write the RDJ receipt, record it in custody and the case journal. The caller
    holds the case lock. A repeated escalation of a case returns its existing escalate receipt."""
    rundir = Path(rundir)
    case_id = case["case_id"]
    mine = [r["record"] for r in custody.rows(rundir, "receipts") if r["record"]["case_id"] == case_id]
    if outcome == "escalate" and mine and mine[-1]["outcome"] == "escalate":
        return read_json(_dir(rundir, "receipts") / (mine[-1]["receipt_id"] + ".json"))
    _commit(rundir, case, state, "authorizing", {"outcome": outcome, **({"reason": reason} if reason else {})})
    case_sha = anchor_check.sha256_file(_case_path(rundir, case_id))
    rows = _finding_rows(case, state)
    summary = _attestation_summary(rundir, case, state)
    existing = len(list(_dir(rundir, "receipts").glob(case_id + "-*.json"))) if _dir(rundir, "receipts").is_dir() else 0
    receipt = {"schema_version": 1, "kind": "rdj-receipt", "receipt_id": f"{case_id}-{existing + 1}",
               "case_sha256": case_sha, "case": {"path": f"rdj/cases/{case_id}.json", "sha256": case_sha},
               "action_digest": case["decision_point"]["action"]["digest"], "gate": case["decision_point"]["gate"],
               "class": case["risk"]["class"], "outcome": outcome, "attestation_summary": summary,
               "policy_sha256": case["risk"]["policy"]["sha256"],
               "open_a_findings": sum(1 for _, _, holding in rows if holding),
               "unresolved_branches": unresolved, "exploratory": _exploratory(case, state),
               "authorized_utc": _now()}
    # The receipt keeps the decision-receipt shape; what else code decided is journaled with it.
    detail = {"advisory_findings": sorted(f["id"] for f, s, _ in rows if s == "advisory"
                                          and f["materiality"] in BLOCKING_CRITIQUE and f["code"] != "no_issue"),
              "independence_basis": _independence_basis(case["risk"]["class"], summary),
              "support_closure_sha256": dc.jdigest(state.get("support_closure") or _closure(case, state)),
              "common_mode": _common_mode(case, state), **({"reason": reason} if reason else {})}
    _dir(rundir, "receipts").mkdir(parents=True, exist_ok=True)
    path = _dir(rundir, "receipts") / (receipt["receipt_id"] + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    receipt_sha = anchor_check.sha256_file(path)
    custody.append(rundir, "receipts", {"receipt_id": receipt["receipt_id"], "sha256": receipt_sha,
                                        "case_id": case_id, "gate": receipt["gate"],
                                        "action_digest": receipt["action_digest"], "outcome": outcome})
    _journal(rundir, case_id, "receipt_written", {"receipt_id": receipt["receipt_id"], "sha256": receipt_sha,
                                                  "outcome": outcome, **detail})
    return receipt


def decision_detail(rundir, receipt_id):
    """What code decided alongside a receipt (advisory findings, independence basis, support-closure
    digest, common-mode sources, escalation reason), read from the custody journal of its case."""
    for row in custody.rows(rundir, "receipts"):
        if row["record"]["receipt_id"] == receipt_id:
            for line in custody.rows(rundir, "journal-" + row["record"]["case_id"]):
                data = line["record"]["data"]
                if line["record"]["event"] == "receipt_written" and data["receipt_id"] == receipt_id:
                    return {k: v for k, v in data.items() if k not in ("receipt_id", "sha256", "outcome")}
    raise ValueError(f"no decision-justification receipt {receipt_id} in custody")


def authorize(rundir, case_id):
    """Code decides. Returns the written receipt or raises ``OpenItems`` naming what is open."""
    rundir = Path(rundir)
    with _lock(rundir, case_id):
        case, state, _ = _load(rundir, case_id)
        _refresh(rundir, case, state)
        errors = authorization_errors(rundir, case, state, refreshed=True)
        codes = {e["code"] for e in errors}
        unresolved = [e for e in errors if e["code"] == "unresolved_branch"]
        hard = [e for e in errors if e["code"] not in SOFT + ("verifier_outcome", "budget_exhausted")]
        for item in unresolved:
            node = _nodes(case)[item["target"]]
            requests = [_unknown_request(u) for u in node["unknowns"]] or [
                {"kind": "evidence", "description": ("Obtain an externally verified anchor for: "
                                                     + node["assertion"])[:dc.MAX_DESCRIPTION]}]
            for request in requests:
                evidence_queue.enqueue(rundir, case_id, source="unresolved_branch", target=node["id"], request=request,
                                       round_=len(case["revisions"]))
        if state["budget_exhausted"]:
            outcome = "escalate"
        elif hard:
            _commit(rundir, case, state, "authorization_refused", {"codes": sorted({e["code"] for e in hard})})
            raise OpenItems(hard)
        elif "verifier_outcome" in codes:
            outcome = case["verification"]["outcome"]
        elif codes & set(SOFT):
            outcome = "gather_evidence"
        else:
            outcome = "authorize"
        receipt = _write_receipt(rundir, case, state, outcome, len(unresolved))
        if outcome == "authorize" and (case["decision_point"]["action_kind"] == "tuning_change"
                                       or case["decision_point"]["gate"] == "deviation"):
            ledger = rundir / "DEVIATIONS.md"
            with ledger.open("a", encoding="utf-8") as stream:
                if ledger.stat().st_size == 0:
                    stream.write("# Deviations\n\n")
                stream.write(deviation_row(case, receipt))
        return receipt


# ---------------------------------------------------------------- gate provider, checks and status

def _current_receipt(rundir, record):
    """Load the case of a custody receipt row and check the receipt still binds it: the receipt file
    matches custody, is journaled, and its case digest is the current case file. Returns the case,
    its state and the receipt, or raises ``ValueError`` with ``code`` set."""
    path = _dir(rundir, "receipts") / (record["receipt_id"] + ".json")
    if anchor_check.sha256_file(path) != record["sha256"]:
        raise ValueError("the receipt file differs from RAVEL custody")
    case, state, lines = _load(rundir, record["case_id"])
    if not any(line["record"]["event"] == "receipt_written" and line["record"]["data"]["sha256"] == record["sha256"]
               for line in lines):
        raise ValueError("the receipt is not in the case journal")
    receipt = read_json(path)
    if receipt.get("case_sha256") != anchor_check.sha256_file(_case_path(rundir, record["case_id"])):
        error = ValueError("the case changed after this receipt; authorize the current case again")
        error.code = "rdj_case_changed"
        raise error
    return case, state, receipt


def _gate_decision(rundir, gate, action):
    """``(errors, accepted)`` for one gate check; ``accepted`` is the one authorize receipt that
    passed every rule (with its case), or None. ``gate_errors`` and ``authorizing_receipt`` both
    decide through this single path."""
    rundir = Path(rundir)
    fix = ("ravel rdj case --rundir <run> --open ...; answer with ravel rdj next/answer; run the roles with "
           "ravel rdj run-roles; then ravel rdj authorize")
    try:
        canonical = canonical_gate(gate)
    except ValueError as exc:
        return [GateError("rdj_unknown_gate", gate, PROVIDER, str(exc), "map the gate name in data/rdj/policy.json")], None
    digest = action.get("digest") if isinstance(action, dict) else None
    try:
        required, _ = compute_class(rundir, gate, action, action.get("facts"))
        rows = [r for r in custody.rows(rundir, "receipts")
                if r["record"]["action_digest"] == digest and r["record"]["gate"] == canonical]
        policy_sha = anchor_check.policy_pin()["sha256"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [GateError("rdj_unreadable", canonical, PROVIDER, f"decision-justification records unreadable: {exc}",
                          fix)], None
    if not rows:
        return [GateError("rdj_receipt_missing", canonical, PROVIDER,
                          f"no decision-justification receipt at {canonical} for this exact action "
                          f"(digest {str(digest)[:12]})", fix)], None
    errors = []
    for row in rows:
        record = row["record"]
        pins = (f"rdj/cases/{record['case_id']}.json",)
        try:
            case, state, receipt = _current_receipt(rundir, record)
            point = case["decision_point"]
            if point["gate"] != canonical or point["action"]["digest"] != digest:
                raise ValueError("the case decided a different gate or action")
            if action.get("kind") is not None and action["kind"] != point["action_kind"]:
                raise ValueError("the case decided a different action kind")
            if case["risk"]["policy"]["sha256"] != policy_sha:
                raise ValueError("the case was decided under a different policy")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(GateError(getattr(exc, "code", "rdj_case_invalid"), canonical, PROVIDER,
                                    f"receipt {record['receipt_id']}: {exc}", fix, pins))
            continue
        if record["outcome"] != "authorize":
            errors.append(GateError("rdj_not_authorized", canonical, PROVIDER,
                                    f"receipt {record['receipt_id']} outcome is {record['outcome']}", fix, pins))
            continue
        if RANK[case["risk"]["class"]] < RANK[required]:
            errors.append(GateError("rdj_class_too_low", canonical, PROVIDER,
                                    f"case {record['case_id']} is {case['risk']['class']}; this action needs {required}",
                                    fix, pins))
            continue
        items = authorization_errors(rundir, case, state)
        if not items:
            return [], {"receipt": receipt, "receipt_sha256": record["sha256"], "case": case,
                        "case_sha256": receipt["case_sha256"]}
        errors += [GateError("rdj_" + item["code"], canonical, PROVIDER, item["message"], fix, pins) for item in items]
    return errors, None


def gate_errors(rundir, gate, action):
    """Provider "rdj" for ``decision_gate.check``: read-only; refuses without a current authorize receipt.

    Only receipts recorded in custody for this gate and this exact action digest are considered.
    The receipt is only a pointer. Gate, action digest, class and policy pin come from the
    replayed case and its journal; the receipt must be in RAVEL custody, journaled, and bind the
    case as it is now (a later save of the case needs a new authorization). ``action.kind`` must be
    the kind of the bytes about to be executed, derived by the caller, never the proposer's label;
    ``action.floor`` (R0-R3) raises the class the action needs and never lowers it."""
    return _gate_decision(rundir, gate, action)[0]


def authorizing_receipt(rundir, gate, action):
    """The receipt that authorizes ``action`` at ``gate``: exactly the one ``gate_errors`` accepted.

    Returns ``{"receipt", "receipt_sha256", "case", "case_sha256"}`` (the RDJ receipt, its
    custody-recorded digest, the replayed current case and its digest), or None when
    ``gate_errors`` is not empty. Consumers read tuning class and human approval from this case,
    never by rescanning custody."""
    errors, accepted = _gate_decision(rundir, gate, action)
    return None if errors else accepted


def check_case(case):
    """``ravel decision-case`` for a v2 case: replay it, apply every authorization rule, and require
    that its latest receipt authorizes the case exactly as it is now."""
    case_id, rundir = case["case_id"], Path(case["rundir"])
    current = False
    try:
        stored, state, _ = _load(rundir, case_id)
        items = [] if dc.jdigest(stored) == dc.jdigest(case) else [
            _item("case_differs", "the given case differs from the case RAVEL recorded")]
        items += authorization_errors(rundir, stored, state)
        receipts = [r["record"] for r in custody.rows(rundir, "receipts") if r["record"]["case_id"] == case_id]
        if receipts and receipts[-1]["outcome"] == "authorize":
            try:
                _current_receipt(rundir, receipts[-1])
                current = True
            except (OSError, ValueError, KeyError, TypeError) as exc:
                items.append(_item(getattr(exc, "code", "rdj_case_invalid").replace("rdj_", ""), str(exc)))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        items, receipts = [_item("case_unverifiable", str(exc))], []
    return {"kind": "rdj-case-check", "case_id": case_id, "authorized": not items and current, "open_items": items,
            "receipts": [r["receipt_id"] for r in receipts]}


def _view(rundir, case_id):
    """The case and a refreshed, unsaved copy of its state (for the recomputing checks)."""
    case, state, _ = _load(rundir, case_id)
    work, view = deepcopy(case), deepcopy(state)
    if not view["invalidated"]:
        _refresh(rundir, work, view, persist=False)
    return case, state, work, view


def support_closure(rundir, case_id):
    """check:support_closure: the unknown and conflict sets recomputed from the case, its anchors and its queue."""
    _, _, work, view = _view(Path(rundir), case_id)
    return _closure(work, view)


def check_support_closure(rundir, case_id):
    """Items when the recorded support closure differs, byte for byte, from its recomputation."""
    _, state, work, view = _view(Path(rundir), case_id)
    recorded = json.dumps(state.get("support_closure"), sort_keys=True, separators=(",", ":")).encode()
    recomputed = json.dumps(_closure(work, view), sort_keys=True, separators=(",", ":")).encode()
    return [] if recorded == recomputed else [_item("support_closure_mismatch",
                                                    "the recorded support closure differs from its recomputation")]


def common_mode_anchors(rundir, case_id):
    """check:common_mode_anchor: sources shared by two or more material claims (R3 and delivery)."""
    _, _, work, view = _view(Path(rundir), case_id)
    return _common_mode(work, view)


def check_critic_basis(rundir, case_id):
    """check:critic_basis (RDJ half): items for a finding whose recorded basis differs from its
    recomputation, or that holds the case without a verified basis or a requested test."""
    rundir = Path(rundir)
    _, state, work, view = _view(rundir, case_id)
    context = _context(rundir, work, view)
    items = []
    for finding in _findings(work).values():
        basis = critic_basis(rundir, work, finding, context)
        if finding["evidence_class"] in dc.BLOCKING_EVIDENCE and basis != state.get("finding_basis", {}).get(finding["id"]):
            items.append(_item("critic_basis_changed", f"finding {finding['id']}: the recorded basis no longer "
                               f"recomputes ({basis})", finding["id"]))
        status_ = finding_status(work, view, finding)
        if status_ == "blocking" and basis != "verified" and view.get("finding_tests", {}).get(finding["id"]) != "upholds":
            items.append(_item("critic_basis_missing", f"finding {finding['id']} holds the case without a verified "
                               "basis or an upheld test", finding["id"]))
    return items


def status(rundir, case_id):
    """A read-only summary: phase, challenges, pending roles, usage and open items. A case whose
    records do not verify, or are missing, is reported as ``tampered`` (``ravel rdj restore`` rebuilds
    the run copies from custody when custody itself verifies)."""
    rundir = Path(rundir)
    try:
        case, state, _ = _load(rundir, case_id)
    except (CaseTampered, custody.CustodyError, OSError, ValueError, KeyError, TypeError) as exc:
        return {"case_id": case_id, "phase": "tampered",
                "open_items": [_item("case_tampered", f"{type(exc).__name__}: {exc}")]}
    try:
        work, view = deepcopy(case), deepcopy(state)
        if not view["invalidated"]:
            _refresh(rundir, work, view, persist=False)
        challenges = [] if view["invalidated"] else _challenges(work, view)
        roles = _pending_roles(work, view, challenges)
        open_items = authorization_errors(rundir, work, view, refreshed=not view["invalidated"])
    except CaseInvalidated as exc:
        work, view, challenges, roles, open_items = case, {**state, "invalidated": str(exc)}, [], [], []
    except (OSError, ValueError) as exc:
        work, view, challenges, roles, open_items = case, state, [], [], [_item("unreadable", str(exc))]
    cls = work["risk"]["class"]
    phase = ("invalidated" if view["invalidated"] else "budget_exhausted" if view["budget_exhausted"] else
             roles[0] if roles else "proposer" if challenges else "ready" if not open_items else "blocked")
    return {"case_id": case_id, "gate": case["decision_point"]["gate"], "class": cls, "phase": phase,
            "challenges": challenges, "pending_roles": roles, "open_items": open_items,
            "usage": state["usage"], "budget": {"max_model_calls": anchor_check.policy()["classes"][cls]["max_model_calls"],
                                                "reason": state["budget_reason"]},
            "exploratory": _exploratory(work, view),
            "queue": [i["item_id"] for i in evidence_queue.items(rundir, case_id=case_id)],
            "receipts": [r["record"]["receipt_id"] for r in custody.rows(rundir, "receipts")
                         if r["record"]["case_id"] == case_id]}


def run_status(rundir):
    """Every case RAVEL recorded for the run, with the run-wide model-call budget."""
    budgets = anchor_check.policy()["budgets"]
    rows = []
    for record in (r["record"] for r in custody.rows(rundir, "cases")):
        row = status(rundir, record["case_id"])
        rows.append({k: row.get(k) for k in ("case_id", "gate", "class", "phase")})
    calls = len(custody.rows(rundir, "roles"))
    return {"cases": rows, "model_calls": calls,
            "budget": {"max_model_calls_per_run": budgets["max_model_calls_per_run"],
                       "remaining": max(0, budgets["max_model_calls_per_run"] - calls)},
            "open_queue_items": len(evidence_queue.items(rundir, status="open"))}


# ---------------------------------------------------------------- CLI: ravel rdj next|answer|status|case|authorize|queue|run-roles|restore|check

def _read(path):
    return read_json(Path(path)) if path else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ravel rdj", description="Decision justification: open a case for a gated "
                                     "action, answer the code-generated challenges, run the reviewer roles on a "
                                     "receipted host, and authorize by code.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("next", "print the challenges the proposer must answer"),
                       ("answer", "apply proposer answers from a JSON file"),
                       ("status", "show one case, or every case in the run"),
                       ("case", "show a case, or open one with --open"),
                       ("authorize", "let code decide and write the receipt"),
                       ("queue", "list the evidence work items"),
                       ("run-roles", "run the pending reviewer roles on a configured agent host"),
                       ("run", "run or resume the RDJ case graph; authorize only by code"),
                       ("restore", "rebuild a case's run records from RAVEL custody after an interrupted save"),
                       ("check", "recompute the support closure, critic basis and common-mode anchors of a case")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--rundir", type=Path, required=True)
        command.add_argument("--case-id", required=name in ("next", "answer", "authorize", "run-roles", "run", "restore",
                                                             "check"))
        if name == "answer":
            command.add_argument("--answers", type=Path, required=True)
        if name == "case":
            command.add_argument("--open", action="store_true")
            command.add_argument("--gate")
            for option in ("--action", "--proposer", "--facts", "--declared", "--tuning"):
                command.add_argument(option, type=Path)
        if name in ("run-roles", "run"):
            command.add_argument("--host-config", type=Path, required=True,
                                 help="agent host configuration (the same file ravel agent-graph uses)")
            command.add_argument("--model", required=True)
            command.add_argument("--reasoning-effort", default="medium")
        if name == "run":
            command.add_argument("--responses", type=Path, help="typed graph resume mapping as JSON")
            command.add_argument("--edge-batch-size", type=int, default=64)
            command.add_argument("--workers", type=int, default=1)
            command.add_argument("--campaign", type=Path)
            command.add_argument("--campaign-charge", type=Path, help="explicit per-call resource vector JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "next":
            result = next_challenges(args.rundir, args.case_id)
        elif args.command == "answer":
            result = answer(args.rundir, args.case_id, _read(args.answers))
        elif args.command == "status":
            result = status(args.rundir, args.case_id) if args.case_id else run_status(args.rundir)
        elif args.command == "authorize":
            result = authorize(args.rundir, args.case_id)
        elif args.command == "queue":
            result = evidence_queue.items(args.rundir, case_id=args.case_id)
        elif args.command in ("run-roles", "run"):
            from .agent_host import AgentHost
            host = AgentHost.from_config(read_json(args.host_config))
            custody.register_host(args.rundir, host.identity)  # the operator path registers its host
            dispatcher = AgentHostDispatcher(host, model=args.model, reasoning_effort=args.reasoning_effort)
            if args.command == "run":
                from .graphs.rdj import run
                result = run(args.rundir, args.case_id, dispatcher, authorize=True, interactive=True,
                             respond=_read(args.responses), edge_batch_size=args.edge_batch_size, workers=args.workers,
                             campaign=args.campaign, campaign_charge=_read(args.campaign_charge))
            else:
                result = run_roles(args.rundir, args.case_id, dispatcher)
        elif args.command == "restore":
            result = restore(args.rundir, args.case_id)
        elif args.command == "check":
            result = {"support_closure": check_support_closure(args.rundir, args.case_id),
                      "critic_basis": check_critic_basis(args.rundir, args.case_id),
                      "common_mode_anchors": common_mode_anchors(args.rundir, args.case_id)}
        elif args.open:
            if not (args.gate and args.action and args.proposer):
                parser.error("--open needs --gate, --action and --proposer")
            case_id = open_case(args.rundir, args.gate, _read(args.action), _read(args.proposer),
                                facts=_read(args.facts), declared=_read(args.declared), tuning=_read(args.tuning))
            result = {"case_id": case_id, "challenges": next_challenges(args.rundir, case_id)}
        else:
            if not args.case_id:
                parser.error("case needs --case-id, or --open")
            result = read_json(_case_path(args.rundir, args.case_id))
    except OpenItems as exc:
        print(json.dumps({"outcome": "refused", "open_items": exc.items}, indent=2))
        return 1
    except (OSError, ValueError) as exc:
        print(f"ravel rdj: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
