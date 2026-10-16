"""Adaptive, evidence-bound audits of a proposed scientific action's justification.

This stores inspectable scientific assertions and brief public rationales, never
private reasoning traces. Code checks the DAG, custody and recorded reviewer
decisions; it does not prove logical entailment or authenticate reviewers.

Schema version 1 is the original audit case and is still read. Version 2 is the
decision-justification case that ``rdj_loop`` builds: an action node, typed
claims, per-edge reviews of entailment, relevance and grounding, anchors whose
verification only code writes, a closed critique taxonomy and Merkle digests
that let a revision re-review only the affected branches.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .diagnostic_plan import binding, bound_file, integer, keys, pointer, read_json, text, unique
from .execution import digest

STATUSES = ("supported", "unresolved", "contradicted")
ANCHORS = ("external_source", "measurement", "user_requirement", "invariant")
TRIGGERS = ("conflict", "novelty", "high_consequence", "unsupported_step")
MAX_NODES, MAX_DEPTH, MAX_EDGES = 256, 64, 4096


def _review(value):
    keys(value, {"reviewer_id", "decision", "reason"}, "review disposition")
    text(value["reviewer_id"], "reviewer id")
    text(value["reason"], "review rationale")
    if value["decision"] not in STATUSES:
        raise ValueError("review decision must be supported/unresolved/contradicted")


def _request(value):
    keys(value, {"kind", "description"}, "specific evidence request")
    if value["kind"] not in ("evidence", "experiment"):
        raise ValueError("request kind must be evidence or experiment")
    text(value["description"], "request description")


def _anchor(value):
    keys(value, {"kind", "artifact", "format", "location", "value"}, "evidence anchor")
    from ..validation.evidence_card import check_rdj_anchor
    check_rdj_anchor(value)
    if value["kind"] not in ANCHORS or value["format"] not in ("json", "text"):
        raise ValueError("unknown evidence anchor kind or format")
    binding(value["artifact"])
    if not isinstance(value["location"], str):
        raise ValueError("anchor location must be a string")
    if value["format"] == "json" and value["location"] and not value["location"].startswith("/"):
        raise ValueError("JSON anchor location must be an RFC6901 pointer")
    if value["format"] == "text":
        if value["location"]:
            raise ValueError("text anchors bind the entire file; use a JSON extract for a field anchor")
        text(value["value"], "text anchor value")
    json.dumps(value["value"], allow_nan=False)


def validate_case(case):
    """Validate a finite, rooted, acyclic scientific assertion DAG."""
    keys(case, {"schema_version", "action", "root", "triggers", "budget", "nodes", "edges"}, "decision case")
    if type(case["schema_version"]) is not int or case["schema_version"] != 1:
        raise ValueError("decision-case schema_version must be integer 1")
    text(case["action"], "proposed action")
    text(case["root"], "root claim")
    if not isinstance(case["triggers"], list) or not case["triggers"]:
        raise ValueError("adaptive audit needs at least one material trigger")
    seen_triggers = set()
    for trigger in case["triggers"]:
        keys(trigger, {"kind", "reason"}, "audit trigger")
        if trigger["kind"] not in TRIGGERS or trigger["kind"] in seen_triggers:
            raise ValueError("unknown or duplicate audit trigger")
        seen_triggers.add(trigger["kind"])
        text(trigger["reason"], "trigger reason")
    keys(case["budget"], {"max_nodes", "max_depth"}, "audit budget")
    integer(case["budget"]["max_nodes"], "node budget")
    integer(case["budget"]["max_depth"], "depth budget", zero=True)
    if case["budget"]["max_nodes"] > MAX_NODES or case["budget"]["max_depth"] > MAX_DEPTH:
        raise ValueError("audit budget exceeds finite engine limits (256 nodes, 64 edges deep)")
    if not isinstance(case["nodes"], list) or not case["nodes"]:
        raise ValueError("decision case needs nodes")
    if len(case["nodes"]) > case["budget"]["max_nodes"]:
        raise ValueError("decision case exceeds node budget")
    nodes = {}
    for node in case["nodes"]:
        keys(node, {"id", "author_id", "assertion", "rationale", "material", "assumptions", "unknowns", "anchors", "review"}, "claim node")
        node_id = text(node["id"], "claim id")
        if node_id in nodes:
            raise ValueError("duplicate claim node")
        nodes[node_id] = node
        text(node["assertion"], "scientific assertion")
        text(node["rationale"], "public rationale")
        if type(node["material"]) is not bool or (node_id == case["root"] and node["material"] is not True):
            raise ValueError("material must be boolean; the action's root is material")
        _review(node["review"])
        text(node["author_id"], "proposition author")
        if node["review"]["reviewer_id"] == node["author_id"]:
            raise ValueError("proposition author cannot review their own assertion")
        for field in ("assumptions", "unknowns", "anchors"):
            if not isinstance(node[field], list):
                raise ValueError(f"{field} must be a list")
        for assumption in node["assumptions"]:
            keys(assumption, {"statement", "disposition", "reason"}, "material assumption")
            text(assumption["statement"], "assumption")
            text(assumption["reason"], "assumption rationale")
            if assumption["disposition"] not in ("accepted", "unresolved", "rejected"):
                raise ValueError("assumption disposition must be accepted/unresolved/rejected")
        for unknown in node["unknowns"]:
            keys(unknown, {"question", "request"}, "material unknown")
            text(unknown["question"], "unknown question")
            _request(unknown["request"])
        for anchor in node["anchors"]:
            _anchor(anchor)
    if case["root"] not in nodes:
        raise ValueError("root claim is absent")
    if not isinstance(case["edges"], list):
        raise ValueError("edges must be a list")
    if len(case["edges"]) > MAX_EDGES:
        raise ValueError("decision case exceeds finite edge limit")
    adjacency, seen = {node_id: [] for node_id in nodes}, set()
    for edge in case["edges"]:
        keys(edge, {"parent", "child", "author_id", "rationale", "review", "request"}, "justification edge")
        if edge["parent"] not in nodes or edge["child"] not in nodes:
            raise ValueError("edge names an absent claim")
        pair = (edge["parent"], edge["child"])
        if pair in seen:
            raise ValueError("duplicate justification edge")
        seen.add(pair)
        adjacency[edge["parent"]].append(edge)
        text(edge["rationale"], "edge public rationale")
        _review(edge["review"])
        text(edge["author_id"], "edge author")
        if edge["review"]["reviewer_id"] in {edge["author_id"], nodes[edge["parent"]]["author_id"], nodes[edge["child"]]["author_id"]}:
            raise ValueError("supporting edge needs review separate from proposition authors")
        if edge["request"] is not None:
            _request(edge["request"])
        if edge["review"]["decision"] == "unresolved" and edge["request"] is None:
            raise ValueError("unresolved justification needs a specific evidence/experiment request")
        if nodes[edge["parent"]]["material"] and not nodes[edge["child"]]["material"]:
            raise ValueError("a context-only claim cannot support a material action")
    reached, active, heights = set(), set(), {}
    def walk(node_id):
        if node_id in active:
            raise ValueError("cyclic claim justification")
        if node_id in heights:
            return heights[node_id]
        active.add(node_id)
        reached.add(node_id)
        height = max((1 + walk(edge["child"]) for edge in adjacency[node_id]), default=0)
        active.remove(node_id)
        heights[node_id] = height
        return height
    if walk(case["root"]) > case["budget"]["max_depth"]:
        raise ValueError("decision case exceeds depth budget")
    if reached != set(nodes):
        raise ValueError("unreachable claims are not part of this action's decision case")
    return json.loads(json.dumps(case, allow_nan=False))


def evaluate_case(case, base_dir="."):
    """Audit custody and recorded dispositions; unsupported branches become requests.

    ``status`` describes this justification case, not the truth of the action or
    the root assertion. Reviewer decisions remain scientific judgments.
    """
    case = validate_case(case)
    nodes = {node["id"]: node for node in case["nodes"]}
    adjacency = {node_id: [] for node_id in nodes}
    for edge in case["edges"]:
        adjacency[edge["parent"]].append(edge)
    reports, obligations, anchor_reports = {}, [], []
    def obligation(node_id, reason, request=None):
        obligations.append({"claim_id": node_id, "reason": reason, "request": request or {
            "kind": "evidence", "description": "Obtain a bound source, measurement, user requirement or invariant for: " + nodes[node_id]["assertion"]}})
    def visit(node_id):
        if node_id in reports:
            return reports[node_id]["status"]
        node = nodes[node_id]
        states = [node["review"]["decision"]]
        if node["review"]["decision"] == "unresolved":
            obligation(node_id, node["review"]["reason"])
        for anchor in node["anchors"]:
            report = {"claim_id": node_id, "kind": anchor["kind"], "artifact": anchor["artifact"], "location": anchor["location"]}
            try:
                path = bound_file(anchor["artifact"], base_dir)
                actual = pointer(read_json(path), anchor["location"]) if anchor["format"] == "json" else path.read_text()
                # Bind JSON type as well as value: true is not the measurement 1.
                if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(anchor["value"], sort_keys=True, allow_nan=False):
                    raise ValueError("anchor field differs from recorded evidence value")
                bound_file(anchor["artifact"], base_dir)
                report["status"] = "supported"
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                report.update(status="contradicted", reason=str(exc))
                states.append("contradicted")
                obligation(node_id, "Evidence custody/field check failed: " + str(exc))
            anchor_reports.append(report)
        for assumption in node["assumptions"]:
            if assumption["disposition"] == "rejected":
                states.append("contradicted")
                obligation(node_id, "Rejected material assumption: " + assumption["statement"])
            elif assumption["disposition"] == "unresolved":
                states.append("unresolved")
                obligation(node_id, "Unresolved material assumption: " + assumption["statement"])
        for unknown in node["unknowns"]:
            states.append("unresolved")
            obligation(node_id, unknown["question"], unknown["request"])
        if not adjacency[node_id] and not node["anchors"]:
            states.append("unresolved")
            obligation(node_id, "Terminal assertion has no external evidence anchor.")
        for edge in adjacency[node_id]:
            child_status = visit(edge["child"])
            states.append(edge["review"]["decision"])
            if edge["review"]["decision"] != "supported":
                obligation(node_id, "Supporting claim does not establish its parent: " + edge["review"]["reason"], edge["request"])
            if child_status != "supported":
                # A bad premise removes support; it does not logically refute the parent.
                states.append("unresolved")
                obligation(node_id, "Supporting claim remains " + child_status + ": " + edge["child"], edge["request"])
        status = "contradicted" if "contradicted" in states else "unresolved" if "unresolved" in states else "supported"
        reports[node_id] = {"id": node_id, "assertion": node["assertion"], "status": status,
                            "reviewer_decision": node["review"]["decision"]}
        return status
    status = visit(case["root"])
    return {"schema_version": 1, "kind": "scientific_decision_case", "case_sha256": digest(case),
            "action": case["action"], "root": case["root"], "status": status,
            "nodes": list(reports.values()), "anchors": anchor_reports, "obligations": obligations,
            "budget": case["budget"], "triggers": case["triggers"], "review_required": True,
            "logical_entailment_proven": False, "physics_validated": False,
            "limitations": ["Structure and recorded decisions are audited; scientific entailment is not proven.",
                            "File hashes do not authenticate the external source or reviewer identity.",
                            "Accepted assumptions remain assumptions, not measured facts."]}


# ---------------------------------------------------------------- schema version 2

CASE_KIND = "rdj-decision-case"
NODE_KINDS = ("action", "claim", "assumption", "alternative")
RELATIONS = ("supports", "rules_out", "chosen_over")
ENTAILMENT = ("holds", "partial", "fails")
RELEVANCE = ("relevant", "weak", "irrelevant")
GROUNDING = ("anchored", "needs_depth", "generated_only")
CRITIQUE_CODES = ("unsupported_claim", "missing_evidence", "alternative_not_considered", "contradiction",
                  "risk_underestimated", "chain_stopped_early", "decision_does_not_follow", "self_grounding",
                  "unmarked_choice", "circular_justification", "irrelevant_support", "post_hoc_rationalization",
                  "no_issue")
ANCHOR_KINDS = ("tool_output", "measurement", "input_artifact", "retrieved_document", "user_requirement",
                "invariant", "external_fact")
VERIFIED = (None, "external", "generated", "invalid")
CLASSES = ("R0", "R1", "R2", "R3")
CONFIDENCE = (None, "low", "medium", "high")
ATTESTATIONS = ("transport_attested", "host_attested", "self_attested", "human_manual")
ATTESTATION_RANK = {"self_attested": 0, "host_attested": 1, "human_manual": 1, "transport_attested": 2}
OBSERVED_LABELS = {"remote_transport_observed": "transport_attested", "local_transport_observed": "transport_attested",
                   "host_attested_external": "host_attested"}
REQUEST_KINDS = ("evidence", "experiment", "requirement_clarification")
MATERIALITY = ("A", "B", "C")
OUTCOMES = ("authorize", "escalate", "gather_evidence")
RESOLVED = ("yes", "no", "new_issue")
EVIDENCE_CLASSES = ("new_receipt", "code_check", "cited", "opinion")
BLOCKING_EVIDENCE = ("new_receipt", "code_check")
TEST_REQUESTS = ("evidence", "experiment")
INPUT_ARTIFACT_ROLES = ("board_head",)
MAX_BROKER_CALLS = 64
TUNING_CLASSES = ("recipe_restoration", "implementation_correction", "calibration", "new_approximation")
CASE_KEYS = {"schema_version", "kind", "case_id", "rundir", "decision_point", "risk", "proposal", "nodes", "edges",
             "anchors", "critique", "revisions", "verification"}
NODE_KEYS = {"id", "kind", "assertion", "rationale", "material", "round", "author", "confidence", "anchors",
             "assumptions", "unknowns", "recommends_choice"}
EDGE_KEYS = {"id", "parent", "child", "round", "challenge", "relation", "author", "review"}
ANCHOR_KEYS = {"id", "kind", "binding", "locator", "value", "quantity", "verified"}
FINDING_KEYS = {"id", "code", "targets", "materiality", "evidence_class", "evidence_locators", "request"}
REVIEW_KEYS = {"reviewer", "edge_sha256", "entailment", "relevance", "grounding", "code", "reason", "request"}
REVISION_KEYS = {"round", "addresses", "changed_nodes", "changed_edges", "diff"}
BLOCKING_MATERIALITY = ("A", "B")
MAX_PATHS = 4096
MAX_DESCRIPTION, MAX_REASON = 300, 1000
LOCATOR = re.compile(r"[A-Za-z0-9_.:/#>@+-]{1,200}")
FINDING_ID = re.compile(r"[A-Za-z0-9_.-]{1,40}")
ABBREVIATIONS = re.compile(r"\b(e\.g|i\.e|etc|vs|cf|approx|incl)\.", re.IGNORECASE)


def jdigest(value):
    """The shared digest of a JSON value."""
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _sha(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase sha256")
    return value


def actor(value, label="actor"):
    keys(value, {"actor_id", "session_receipt", "attestation"}, label)
    text(value["actor_id"], label + " id")
    if value["session_receipt"] is not None:
        text(value["session_receipt"], label + " session receipt")
    if value["attestation"] not in ATTESTATIONS:
        raise ValueError(f"{label} attestation must be one of {ATTESTATIONS}")
    return value


def label_for(execution_mode, verified_label):
    """The attestation label of one role call from its execution mode (an observation, never a label).

    ``transport_attested_cli`` is ``transport_attested`` only when the transport re-verification that
    the worker dispatcher recorded at registration gave ``transport_attested``; host-observed HTTP
    transports are ``transport_attested``; a host-mediated external result is ``host_attested``.
    Anything else, relay responses of schema 1 or 2 included, is ``self_attested``."""
    if execution_mode == "transport_attested_cli":
        return "transport_attested" if verified_label == "transport_attested" else "self_attested"
    return OBSERVED_LABELS.get(execution_mode, "self_attested") if isinstance(execution_mode, str) else "self_attested"


def independent(label):
    """Whether a role call with this attestation label counts toward an independent review."""
    return label in ATTESTATIONS and label != "self_attested"


def request_v2(value, label="request"):
    """A typed request. ``max_broker_calls`` (optional) bounds the broker calls a critic's
    own discriminating test may spend; the policy sets the cap."""
    if value is None:
        return None
    keys(value, {"kind", "description", *({"max_broker_calls"} if isinstance(value, dict)
                                          and "max_broker_calls" in value else ())}, label)
    if value["kind"] not in REQUEST_KINDS:
        raise ValueError(f"{label} kind must be one of {REQUEST_KINDS}")
    _line(value["description"], label + " description", MAX_DESCRIPTION)
    if "max_broker_calls" in value:
        calls = value["max_broker_calls"]
        if type(calls) is not int or not 0 <= calls <= MAX_BROKER_CALLS:
            raise ValueError(f"{label} max_broker_calls is an integer from 0 to {MAX_BROKER_CALLS}")
    return value


def may_block(finding):
    """The evidence-class rule: an A or B finding can hold authorization only when it
    rests on a new receipt or a code check, or asks for a discriminating test (an evidence or
    experiment request) whose result is pending or upholds it. ``cited`` and ``opinion``
    findings without such a request are advisory. Whether a basis verifies, and what a
    requested test returned, is decided by the loop (``rdj_loop.finding_status``)."""
    if finding.get("materiality") not in BLOCKING_MATERIALITY or finding.get("code") == "no_issue":
        return False
    request = finding.get("request")
    return finding.get("evidence_class") in BLOCKING_EVIDENCE or (request is not None
                                                                  and request.get("kind") in TEST_REQUESTS)


def _line(value, label, maximum):
    text(value, label)
    if len(value) > maximum or "\n" in value or "\r" in value:
        raise ValueError(f"{label} is one line of at most {maximum} characters")
    return value


def one_sentence(value):
    """True when ``value`` is a single sentence (common abbreviations such as e.g. allowed)."""
    body = ABBREVIATIONS.sub("abbr", value.strip()).rstrip(".!?")
    return not re.search(r"[.!?]\s+\S", body)


def edge_review(value):
    """One reviewer verdict for one hop; the closed shape reviewers must return."""
    keys(value, REVIEW_KEYS, "edge review")
    actor(value["reviewer"], "edge reviewer")
    _sha(value["edge_sha256"], "reviewed edge digest")
    if value["entailment"] not in ENTAILMENT or value["relevance"] not in RELEVANCE or value["grounding"] not in GROUNDING:
        raise ValueError("edge review entailment, relevance or grounding is outside the closed vocabulary")
    if value["code"] not in CRITIQUE_CODES:
        raise ValueError("edge review code is outside the critique taxonomy")
    _line(value["reason"], "edge review reason", MAX_REASON)
    request_v2(value["request"], "edge review request")
    affirmative = (value["entailment"] == "holds" and value["relevance"] == "relevant"
                   and value["grounding"] == "anchored")
    if affirmative and value["code"] != "no_issue":
        raise ValueError(f"edge review code {value['code']} contradicts an affirmative verdict")
    if not affirmative and value["code"] == "no_issue":
        raise ValueError("edge review code no_issue is given exactly when the hop holds, is relevant and is anchored")
    return value


def critique(value):
    """The critic's closed output: findings only, never plan text (T6)."""
    keys(value, {"reviewer", "findings"}, "critique")
    actor(value["reviewer"], "critic")
    if not isinstance(value["findings"], list):
        raise ValueError("critique findings must be a list")
    seen = set()
    for finding in value["findings"]:
        allowed = FINDING_KEYS | ({"alternative"} if isinstance(finding, dict)
                                  and finding.get("code") == "alternative_not_considered" else set())
        if type(finding) is not dict or set(finding) - allowed or FINDING_KEYS - set(finding):
            missing = " (every finding states its evidence class)" if isinstance(finding, dict) \
                and "evidence_class" not in finding else ""
            raise ValueError(f"critique finding requires exactly {sorted(FINDING_KEYS)}"
                             " (plus 'alternative' for alternative_not_considered)" + missing)
        if not FINDING_ID.fullmatch(text(finding["id"], "finding id")) or finding["id"].startswith("E:"):
            raise ValueError("finding id is a short identifier")
        if finding["id"] in seen:
            raise ValueError("duplicate finding id")
        seen.add(finding["id"])
        if finding["code"] not in CRITIQUE_CODES:
            raise ValueError("critique finding code is outside the closed taxonomy")
        if finding["materiality"] not in MATERIALITY:
            raise ValueError("finding materiality must be A, B or C")
        if finding["evidence_class"] not in EVIDENCE_CLASSES:
            raise ValueError(f"finding evidence class must be one of {EVIDENCE_CLASSES}")
        if not isinstance(finding["targets"], list) or not all(isinstance(t, str) for t in finding["targets"]):
            raise ValueError("finding targets must be a list of node or edge ids")
        if not finding["targets"] and finding["code"] != "no_issue":
            raise ValueError("a finding names at least one target node or edge")
        if not isinstance(finding["evidence_locators"], list) or len(finding["evidence_locators"]) > 32 \
                or not all(isinstance(t, str) and LOCATOR.fullmatch(t) for t in finding["evidence_locators"]):
            raise ValueError("finding evidence locators are case ids or run paths, not free text")
        request_v2(finding["request"], "finding request")
        if finding["code"] == "alternative_not_considered":
            name = _line(finding.get("alternative"), "named alternative", MAX_DESCRIPTION)
            if not one_sentence(name):
                raise ValueError("the critic names an alternative in one sentence and stops there")
    return value


def verification(value, findings, revised):
    """The verifier's closed output. ``findings`` are the critique findings (or their ids);
    a finding that may block (``may_block``) can be resolved only if a revision addressed it."""
    rows = {f["id"]: f for f in findings} if all(isinstance(f, dict) for f in findings) else {f: None for f in findings}
    finding_ids = list(rows)
    keys(value, {"reviewer", "per_finding", "outcome"}, "verification")
    actor(value["reviewer"], "verifier")
    if value["outcome"] not in OUTCOMES:
        raise ValueError("verifier outcome must be authorize, escalate or gather_evidence")
    if not isinstance(value["per_finding"], list):
        raise ValueError("verifier per_finding must be a list")
    covered = set()
    for row in value["per_finding"]:
        keys(row, {"finding_id", "resolved", "reason"}, "verifier finding row")
        if row["finding_id"] not in finding_ids:
            raise ValueError("the verifier cannot add findings; new_issue must name a finding whose revision it concerns")
        if row["resolved"] not in RESOLVED:
            raise ValueError("verifier resolution must be yes, no or new_issue")
        if row["resolved"] == "new_issue" and row["finding_id"] not in revised:
            raise ValueError("a new_issue must be tied to a revision")
        finding = rows[row["finding_id"]]
        if row["resolved"] == "yes" and finding is not None and may_block(finding) \
                and row["finding_id"] not in revised:
            raise ValueError(f"finding {row['finding_id']} cannot be resolved: no revision addressed it")
        _line(row["reason"], "verifier reason", MAX_REASON)
        if row["finding_id"] in covered:
            raise ValueError("duplicate verifier row for one finding")
        covered.add(row["finding_id"])
    if covered != set(finding_ids):
        raise ValueError("the verifier must rule on every finding")
    return value


def evidence_obligations(value):
    """Required anchor kinds, discharged by current externally grounded supporting evidence.

    The optional field is deliberately closed: an empty or malformed declaration cannot
    opt an otherwise untyped branch out of its legacy depth requirements.
    """
    if not isinstance(value, list) or not value or any(kind not in ANCHOR_KINDS for kind in value) \
            or len(set(value)) != len(value):
        raise ValueError("evidence obligations are a nonempty list of unique anchor kinds")
    return value


def validate_case_v2(case):
    """Structural checks of a version-2 case: closed vocabularies, one root, acyclic, bounded."""
    keys(case, CASE_KEYS | {k for k in ("rca", "input_artifacts") if k in case}, "decision case v2")
    if type(case["schema_version"]) is not int or case["schema_version"] != 2 or case["kind"] != CASE_KIND:
        raise ValueError("decision case v2 requires schema_version 2 and kind " + CASE_KIND)
    text(case["case_id"], "case id")
    point = case["decision_point"]
    keys(point, {"gate", "action_kind", "action", *(k for k in ("tuning", "exploration", "review_scope") if k in point)},
         "decision point")
    text(point["gate"], "gate")
    text(point["action_kind"], "action kind")
    keys(point["action"], {"summary", "digest", "pins"}, "decided action")
    text(point["action"]["summary"], "action summary")
    _sha(point["action"]["digest"], "action digest")
    for pin in point["action"]["pins"]:
        binding(pin)
    if "review_scope" in point:
        binding(point["review_scope"])
        if "exploration" in point:
            raise ValueError("exploration decisions cannot carry a portable review scope")
    if "exploration" in point:
        exploration = point["exploration"]
        keys(exploration, {"scope", "contract"}, "exploration decision")
        if exploration["scope"] != "exploration_only" or point["gate"] != "research_choice" \
                or point["action_kind"] != "screening_choice":
            raise ValueError("exploration-only decisions select a research_choice screening_choice")
        binding(exploration["contract"])
    if point["action_kind"] == "tuning_change":
        tuning = point.get("tuning")
        keys(tuning, {"class", "parameter", "from", "to", "reason"}, "tuning change")
        if tuning["class"] not in TUNING_CLASSES:
            raise ValueError(f"tuning change class must be one of {TUNING_CLASSES}")
        text(tuning["parameter"], "tuned parameter")
        text(tuning["reason"], "tuning reason")
    elif "tuning" in point:
        raise ValueError("only a tuning_change action carries a tuning record")
    keys(case["risk"], {"class", "computed_factors", "declared_factors", "policy"}, "risk")
    if case["risk"]["class"] not in CLASSES:
        raise ValueError("risk class must be R0-R3")
    binding(case["risk"]["policy"])
    for artifact in case.get("input_artifacts", ()):
        if type(artifact) is not dict or artifact.get("role") not in INPUT_ARTIFACT_ROLES:
            raise ValueError(f"an input artifact has a role from {INPUT_ARTIFACT_ROLES}")
        keys(artifact, {"role", "path", "sha256"}, "input artifact")
        binding({k: artifact[k] for k in ("path", "sha256")})
    if "input_artifacts" in case and not isinstance(case["input_artifacts"], list):
        raise ValueError("input artifacts are a list")
    keys(case["proposal"], {"node_id", "committed_event"}, "proposal")
    _sha(case["proposal"]["committed_event"], "committed proposal event")
    anchors = {}
    for anchor in case["anchors"]:
        keys(anchor, ANCHOR_KEYS, "anchor")
        if text(anchor["id"], "anchor id") in anchors:
            raise ValueError("duplicate anchor id")
        if anchor["kind"] not in ANCHOR_KINDS or anchor["verified"] not in VERIFIED:
            raise ValueError("unknown anchor kind or verification state")
        if type(anchor["binding"]) is not dict or not isinstance(anchor["locator"], str):
            raise ValueError("anchor binding must be an object and locator a string")
        json.dumps(anchor["value"], allow_nan=False)
        anchors[anchor["id"]] = anchor
    nodes = {}
    for node in case["nodes"]:
        keys(node, NODE_KEYS | {key for key in ("evidence_obligations", "review_context_sha256") if key in node},
             "case node")
        if "review_context_sha256" in node:
            if "review_scope" not in point:
                raise ValueError("review context requires a bound review scope")
            _sha(node["review_context_sha256"], "review context digest")
        if "evidence_obligations" in node:
            evidence_obligations(node["evidence_obligations"])
        if text(node["id"], "node id") in nodes:
            raise ValueError("duplicate node id")
        if node["kind"] not in NODE_KINDS or node["confidence"] not in CONFIDENCE:
            raise ValueError("unknown node kind or confidence")
        if (node["kind"] == "action") != (node["id"] == case["proposal"]["node_id"]):
            raise ValueError("exactly the proposal node is the action")
        text(node["assertion"], "node assertion")
        text(node["rationale"], "node rationale")
        if type(node["material"]) is not bool or type(node["recommends_choice"]) is not bool:
            raise ValueError("material and recommends_choice must be boolean")
        integer(node["round"], "node round", zero=True)
        actor(node["author"], "node author")
        if any(a not in anchors for a in node["anchors"]):
            raise ValueError("node names an absent anchor")
        for row in node["assumptions"]:
            text(row, "node assumption")
        for row in node["unknowns"]:
            keys(row, {"question", "request"}, "node unknown")
            text(row["question"], "unknown question")
            request_v2(row["request"], "unknown request")
        nodes[node["id"]] = node
    root = case["proposal"]["node_id"]
    if root not in nodes or nodes[root]["material"] is not True:
        raise ValueError("the action node is absent or not material")
    if len(nodes) > MAX_NODES or len(case["edges"]) > MAX_EDGES:
        raise ValueError("decision case exceeds finite engine limits")
    adjacency, seen_ids, pairs = {n: [] for n in nodes}, set(), set()
    for edge in case["edges"]:
        keys(edge, EDGE_KEYS, "case edge")
        if text(edge["id"], "edge id") in seen_ids or (edge["parent"], edge["child"]) in pairs:
            raise ValueError("duplicate edge")
        seen_ids.add(edge["id"]); pairs.add((edge["parent"], edge["child"]))
        if edge["parent"] not in nodes or edge["child"] not in nodes or edge["child"] == root:
            raise ValueError("edge names an absent node or points at the action")
        if edge["relation"] not in RELATIONS:
            raise ValueError("unknown edge relation")
        if (edge["relation"] == "chosen_over") != (nodes[edge["child"]]["kind"] == "alternative"):
            raise ValueError("alternative nodes are attached with chosen_over, and only they are")
        if edge["relation"] == "rules_out" and nodes[edge["parent"]]["kind"] != "alternative":
            raise ValueError("rules_out evidence attaches under an alternative; it never supports the action")
        if edge["relation"] == "supports" and nodes[edge["parent"]]["material"] and not nodes[edge["child"]]["material"]:
            raise ValueError("a non-material claim cannot support a material one")
        text(edge["challenge"], "edge challenge")
        integer(edge["round"], "edge round", zero=True)
        actor(edge["author"], "edge author")
        if edge["review"] is not None:
            edge_review(edge["review"])
        adjacency[edge["parent"]].append(edge["child"])
    active, height, paths = set(), {}, {}
    def walk(node_id):  # memoized: each node is expanded once
        if node_id in height:
            return
        if node_id in active:
            raise ValueError("cyclic decision case")
        active.add(node_id)
        for child in adjacency[node_id]:
            walk(child)
        active.discard(node_id)
        height[node_id] = 1 + max((height[c] for c in adjacency[node_id]), default=-1)
        paths[node_id] = max(1, sum(paths[c] for c in adjacency[node_id]))
        if height[node_id] > MAX_DEPTH:
            raise ValueError("decision case exceeds finite depth")
        if paths[node_id] > MAX_PATHS:
            raise ValueError(f"decision case has more than {MAX_PATHS} root-to-leaf paths")
    walk(root)
    if set(height) != set(nodes):
        raise ValueError("every node must be reachable from the action")
    if case["critique"] is not None:
        critique(case["critique"])
    finding_ids = [f["id"] for f in (case["critique"] or {"findings": []})["findings"]]
    revised = set()
    for revision in case["revisions"]:
        keys(revision, REVISION_KEYS, "revision")
        if any(f not in finding_ids and not (f.startswith("E:") and f[2:] in seen_ids | set(revision["changed_edges"]))
               for f in revision["addresses"]):
            raise ValueError("a revision addresses an unknown finding")
        revised.update(revision["addresses"])
    if case["verification"] is not None:
        verification(case["verification"], (case["critique"] or {"findings": []})["findings"], revised)
    return json.loads(json.dumps(case, allow_nan=False))


def node_content(node, anchors):
    """Own content of a node, with its anchors' current verification (Merkle leaf part)."""
    return {"kind": node["kind"], "assertion": node["assertion"], "rationale": node["rationale"],
            "material": node["material"], "confidence": node["confidence"], "assumptions": node["assumptions"],
            "unknowns": node["unknowns"], "recommends_choice": node["recommends_choice"],
            **({"evidence_obligations": node["evidence_obligations"]} if "evidence_obligations" in node else {}),
            **({"review_context_sha256": node["review_context_sha256"]} if "review_context_sha256" in node else {}),
            "anchors": sorted(jdigest({k: anchors[a][k] for k in ("kind", "binding", "locator", "value",
                                                                   "quantity", "verified")})
                              for a in node["anchors"])}


def merkle(case):
    """Node and edge digests (RDJ §5.2): a node hashes its content, anchors and outgoing edges;
    an edge hashes its content, its parent's own content and its child's digest. An edge review
    binds the edge digest, so a revised parent claim or any change below an edge (content,
    anchors or their verification) invalidates that review."""
    nodes = {n["id"]: n for n in case["nodes"]}
    anchors = {a["id"]: a for a in case["anchors"]}
    out = {n: [] for n in nodes}
    for edge in case["edges"]:
        out[edge["parent"]].append(edge)
    node_d, edge_d = {}, {}
    def node_digest(node_id):
        if node_id not in node_d:
            for edge in out[node_id]:
                edge_d[edge["id"]] = jdigest({"parent": edge["parent"], "child": edge["child"],
                                              "relation": edge["relation"], "challenge": edge["challenge"],
                                              "parent_content": node_content(nodes[edge["parent"]], anchors),
                                              "child_sha256": node_digest(edge["child"])})
            node_d[node_id] = jdigest({"content": node_content(nodes[node_id], anchors),
                                       "edges": sorted(edge_d[e["id"]] for e in out[node_id])})
        return node_d[node_id]
    for node_id in nodes:
        node_digest(node_id)
    return {"nodes": node_d, "edges": edge_d}


def read_any(case, base_dir="."):
    """Version dispatch: v1 cases evaluate as before. A v2 case is checked by the decision
    justification loop (custody, journal replay and every authorization rule), never by
    structure alone: the result says whether it is authorized and lists every open item."""
    version = case.get("schema_version") if isinstance(case, dict) else None
    if version == 1:
        return evaluate_case(case, base_dir)
    if version == 2:
        validate_case_v2(case)
        from .rdj_loop import check_case
        return check_case(case)
    raise ValueError("unknown decision-case schema_version")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = read_any(read_json(args.case), args.case.resolve().parent)
        rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(rendered)
        print(rendered, end="")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"decision case: {exc}\n")
    return 1 if result.get("kind") == "rdj-case-check" and not result["authorized"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
