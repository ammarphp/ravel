"""Decision gates, live physicist steering and the custody records RAVEL dispatchers consult.

Initialization and CHECK-IN recorders retain their epoch-two source contracts.
Live steering applies to every run:

- run initialization: the original prompt as user text and the ``run_init`` input snapshot, which
  binds ``agent_layer_epoch: 2`` against a later downgrade; an intake resolution before CHECK-IN 1
  re-records ``run_init`` for the contract RAVEL itself rewrote;
- CHECK-IN 1: the operator's quoted response as user text and the ``checkin1`` input snapshot. A
  response file custody did not record is refused, never adopted; a later quote (re-approval) is
  recorded as operator text with a ``reapproval`` row in the custody ``steering`` ledger;
- steering: the message as user text plus a structured record in the custody ``steering`` ledger
  (span, effect, affected nodes; mirrored to ``inputs/steering/<n>.json`` for reading) that an RDJ
  ``user_requirement`` anchor cites. Requirements and redirects hold affected work for acknowledgement
  and reconciliation. Scope increases and policy changes require plan reapproval. Pause, veto and
  priority control dispatch; result disposition stays separate from scientific-review acceptance;
- the response path (``ravel respond``): the user's text plus the explicit ``approve``, ``reopen``
  and ``withdraw`` decisions the operator names. Each decision quotes the recorded text.

Wiring: ``check_transition`` calls ``decision_gate.check`` at the wired transitions. R0/R1:
``failed_stage_feedback``, ``research_choice`` and screen dispatch; every entry point of the two
research decisions calls ``require_research_choice`` or ``require_failed_feedback``.
``delegated_dispatch_errors`` is P15: a screen launch needs an R1 RDJ receipt whose action binds the
dispatched bytes and the lease this process holds; ``launch_errors`` is its caller in the launch
authorization. R2/R3 (phase B): on a delegated epoch-two run, ``require_delegated`` decides the full
and scan launch, the delegated CHECK-IN 1 approval and CHECK-IN 2 GO, result packaging and the
submission export. ``GATE_WIRING`` lists every gate as wired or legacy with the condition that
blocks it. ``physics_value_errors`` is PHYS-RDJ; the delegated plan pre-authorization calls it. A
pass on a registered impossible fixture is recorded as a gaming event and refused. ``cost_report``
is the T13 report of RDJ calls and tokens.

The response and steering commands run as the operator's user; until the operator path is
separated from agent sessions this is same-user transport (docs/reference/gate-wiring.md), and
every R3 gate also needs a recorded human approval of its authorizing case.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import shlex
from contextlib import contextmanager, ExitStack
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import rdj_custody as custody
from .decision_gate import GateError
from .state_io import file_lock, atomic_json

PROVIDER = "gate_wiring"
EPOCH = 2
STEERING_RECORDS = "inputs/steering"
PARENT_MIRROR = 'parent-binding.json'
JOURNAL_ROUTES = ('run-initialization', 'study-plan', 'research-study', 'scan-plan', 'graph-scope',
                  'transport-qualification', 'operator')
JOURNAL_INIT_COMMAND = 'ravel gate-wiring steer init --rundir <run>'
STEERING_EFFECTS = ("note", "requirement", "scope_change", "redirect", "pause", "resume", "veto", "priority", "result_disposition")
ACTIONS_DIR = "gate-actions"
R2R3_GATES = ("approve_plan", "launch", "checkin2_accept", "correction", "deviation", "delivery", "final_task",
              "report_integrity", "export", "unblind", "spend_above_ceiling")
R3_GATES = ("delivery", "final_task", "report_integrity", "export", "unblind", "spend_above_ceiling")
WIRED_GATES = ("failed_stage_feedback", "research_choice") + R2R3_GATES
# A scope-change steering record holds every decision that acts under the approved plan.
STEERING_GATES = tuple(g for g in WIRED_GATES if g != "failed_stage_feedback")
# Open: the operator path is not separated from agent sessions, so
# R2/R3 transport is same-user transport and every R3 gate also needs a recorded human approval.
SAME_USER_TRANSPORT = True
# Every decision gate: (class, wired | legacy, transition or the condition that blocks wiring).
# docs/reference/gate-wiring.md carries the same table; a test keeps the two equal.
GATE_WIRING = {
    "failed_stage_feedback": ("R1", "wired", "scientific_judgment.failed_feedback, research_coordinator_decisions.diagnose, research-cycle diagnostic-feedback"),
    "research_choice": ("R1", "wired", "scientific_judgment.research_feedback, research-cycle adjudicate; research_orchestrator calls it before every adjudication"),
    "launch": ("R0-R2", "wired", "launch_authorization: dry and smoke screens through P15, full and scan at R2 on delegated runs; production_executor.launch_errors"),
    "approve_plan": ("R2", "wired", "workflow_state.record_delegated_approval on delegated runs; lifecycle.drive and review.points gate nodes"),
    "checkin2_accept": ("R2", "wired", "workflow_state.record_delegated_go on delegated runs; review_points.accept_checkin2; lifecycle.drive and review.points gate nodes"),
    "correction": ("R2", "legacy", "ravel science-correct admits a correction under physics_review's own bounded approval; no correction action exists for an RDJ case to pin outside the review.points gate node"),
    "deviation": ("R2", "legacy", "no transition records a deviation decision; recipe_ledger consumes the deviation authorizing receipt directly"),
    "delivery": ("R3", "wired", "result_pack on delegated runs, plus a recorded human approval (same-user transport)"),
    "final_task": ("R3", "legacy", "decided only on the review.points CHECK-IN 3 and ml_study gate nodes; verify_pack's final check is physics_review's"),
    "report_integrity": ("R3", "legacy", "decided only on the review.points gate node; no ordinary report transition exists"),
    "export": ("R3", "wired", "submission_export.export on delegated runs, plus a recorded human approval (same-user transport)"),
    "unblind": ("R3", "legacy", "decided only on the ml_study unblind gate node and ml_crossfit; epoch-one contracts are refused"),
    "spend_above_ceiling": ("R3", "wired", "check through require_delegated and the ml_study spend gate node; run_ceilings.charge refuses any charge above the recorded ceiling, which only a custody-recorded CHECK-IN 1 response raises"),
}
# Launch kinds a delegated screen may dispatch (policy class at most R1 for a dry or smoke rung).
SCREEN_KINDS = ("dry_run", "smoke_launch", "single_point_launch", "screening_choice", "reuse_accepted_stage")
VALUE_ORIGINS = ("agent_inferred", "user", "published", "tool_output")


class SteeringRefused(ValueError):
    """Live steering refused a dispatch (pause, veto, hold or missing custody); nothing was started.

    ``launch_refused`` is true when ``steering_dispatch`` itself refused, before its body (the
    launch) ran: no process of that launch exists."""
    launch_refused = False


def _launch_refusal(reason):
    refused = SteeringRefused(reason)
    refused.launch_refused = True
    return refused


class GateRefused(ValueError):
    """A wired gate refused a transition; ``errors`` are the decision-gate errors."""

    def __init__(self, gate, errors):
        self.gate, self.errors = gate, list(errors)
        super().__init__(f"{gate} refused: " + "; ".join(f"{e.provider}:{e.code}: {e.message}" for e in self.errors))


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _contract(rundir):
    path = Path(rundir) / custody.TASK_CONTRACT
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def epoch_two(rundir):
    """True when the run's contract is a release contract (``agent_layer_epoch`` exactly integer 2)."""
    contract = _contract(rundir)
    return contract is not None and type(contract.get("agent_layer_epoch")) is int and contract["agent_layer_epoch"] == EPOCH


def _events(rundir, event):
    return [r for r in custody.rows(rundir, "inputs") if r["record"]["event"] == event]


def _run_init_errors(rundir, gate):
    """F7: an epoch-two contract without a custody run_init row binds nothing (an intake that
    crashed between writing the contract and recording it); it is refused, never decided."""
    if not epoch_two(rundir):
        return []
    try:
        if _events(rundir, "run_init"):
            return []
    except (custody.CustodyError, OSError, ValueError) as exc:
        return [GateError("gate_inputs_invalid", gate, PROVIDER, f"custody is unreadable: {exc}",
                          "Restore the run's custody ledgers.", ("custody:inputs",))]
    return [GateError("run_init_missing", gate, PROVIDER,
                      "the epoch-two contract has no run_init snapshot in custody; its epoch binds nothing",
                      "Start a new run with ravel initiate.", ("custody:inputs:run_init",))]


# ---------------------------------------------------------------- run initialization

def _record_prompt(rundir, contract):
    prompt = contract.get("prompt")
    bound = (contract.get("task_requirements") or {}).get("prompt_sha256")
    if not isinstance(prompt, str) or bound is None:
        return None
    digest = _sha(prompt.encode())
    if custody.user_text_row(rundir, "prompt", custody.TASK_CONTRACT, digest) is None:
        custody.record_user_text(rundir, "prompt", custody.TASK_CONTRACT)
    return digest


def record_run_init(rundir):
    """Record the original prompt and the run_init input snapshot. Called by the release intake
    once the contract is final; returns None for a pre-release contract."""
    if not epoch_two(rundir):
        return None
    prompt = _record_prompt(rundir, _contract(rundir))
    if not _events(rundir, "run_init"):
        custody.record_input_snapshot(rundir, "run_init")
    return {"prompt_sha256": prompt, "run_init": True}


def _snapshot_files(rundir):
    from .rdj_anchor import policy
    pol = policy()
    base = Path(rundir).resolve()
    files = {}
    if (base / "inputs").is_dir():
        for path in sorted((base / "inputs").rglob("*")):
            if path.is_file() and not path.is_symlink():
                if len(files) >= pol["input_snapshot_max_files"]:
                    raise ValueError("the run_init input snapshot exceeds its file limit (policy input_snapshot_max_files)")
                files[path.relative_to(base).as_posix()] = _sha(path.read_bytes())
    written = sorted(r for r in files if any(fnmatch.fnmatchcase(r, p) for p in pol["ravel_written_inputs"]))
    return files, written


def check_resolution(rundir):
    """Refuse an intake resolution once CHECK-IN 1 is recorded or when the contract on disk is not
    the one custody recorded at run_init. Called before RAVEL rewrites a held draft."""
    if _events(rundir, "checkin1"):
        raise ValueError("the intake reached CHECK-IN 1 in custody; start a new run instead of resolving it")
    rows = _events(rundir, "run_init")
    if rows:
        current = _sha((Path(rundir) / custody.TASK_CONTRACT).read_bytes())
        if rows[-1]["record"]["files"].get(custody.TASK_CONTRACT) != current:
            raise ValueError("the held contract differs from the run_init snapshot; it cannot be resolved in place")


def record_intake_resolution(rundir, previous_contract_sha256):
    """Re-record run_init after RAVEL's own intake resolution rewrote a pre-CHECK-IN 1 draft."""
    return record_contract_rewrite(rundir, previous_contract_sha256, reason="intake_resolution")


def record_contract_rewrite(rundir, previous_contract_sha256, *, reason):
    """Re-record run_init after a RAVEL-owned rewrite of a pre-CHECK-IN 1 contract (an intake
    resolution, or ordinary planning such as ``scoped.plan``).

    The previous contract must be the one custody recorded, the run must not have reached
    CHECK-IN 1 and the resolved contract must keep epoch two, so a resolution never launders a
    downgrade. Custody records run_init once; the resolution appends a superseding row through
    the public ledger API (handoff: a first-class supersede in rdj_custody)."""
    rows = _events(rundir, "run_init")
    if not rows:
        # Only the intake records a first run_init; a later rewrite never vouches for a contract
        # custody did not record (an epoch-two run without run_init stays refused).
        return record_run_init(rundir) if reason == "intake_resolution" else None
    if _events(rundir, "checkin1"):
        raise ValueError("the intake reached CHECK-IN 1 in custody; a rewrite cannot re-record run_init")
    last = rows[-1]
    if last["record"]["files"].get(custody.TASK_CONTRACT) != previous_contract_sha256:
        raise ValueError("the resolved draft is not the contract custody recorded at run_init")
    if not epoch_two(rundir):
        raise ValueError("a resolved release contract must keep agent_layer_epoch 2")
    files, written = _snapshot_files(rundir)
    record = {"event": "run_init", "files": files, "ravel_written": written, "unvouched": [],
              "supersedes": {"seq": last.get("seq"), "contract_sha256": previous_contract_sha256},
              "reason": reason}

    def unchanged(existing):
        inputs = [r for r in existing if r["record"]["event"] in ("run_init", "checkin1")]
        if any(r["record"]["event"] == "checkin1" for r in inputs):
            return "the intake reached CHECK-IN 1"
        if inputs[-1]["record"] != last["record"]:
            return "run_init changed during the resolution"
        return None
    _record_prompt(rundir, _contract(rundir))
    return custody.append(rundir, "inputs", record, check=unchanged)


# ---------------------------------------------------------------- CHECK-IN 1 and the response path

def _approval_digest(rundir):
    for rel in ('inputs/checkin1_approval.json', 'inputs/science-approval.json'):
        path = Path(rundir) / rel
        if path.is_file() and not path.is_symlink():
            return _sha(path.read_bytes())
    return None


def _refuse_response(rundir, raw, reason):
    record = {"rundir": str(Path(rundir).resolve()), "path": custody.CI1_RESPONSE, "reason": reason,
              "sha256": None if raw is None else _sha(raw), "utc": _utc()}
    _append_line(_store("refused-responses.jsonl"), record)
    raise ValueError(f"an unrecorded CHECK-IN 1 response file exists at {custody.CI1_RESPONSE}; RAVEL records only "
                     "the operator's quoted response. Remove the file and approve with --quote "
                     "(the refusal is logged).")


def refused_responses(rundir):
    run = str(Path(rundir).resolve())
    return [r for r in _read_lines(_store("refused-responses.jsonl")) if r["rundir"] == run]


def record_checkin1(rundir, *, quote=None, scripted=False):
    """Record the operator's CHECK-IN 1 response as user text and take the checkin1 snapshot.

    Only the quote passed on the operator path (``ravel approve --quote``, ``ravel gate-wiring
    checkin1 --quote``) becomes user text. A response file custody did not record, whoever wrote
    it, is refused and logged, scripted or not. A later quote after the first response is a
    re-approval: it is recorded as operator text and appends an ``approval`` row (with the current
    approval digest) to the custody steering ledger. That row clears a pending scope hold only when
    the approval writer produced a receipt that differs from the one current at the steering event;
    a row for an unchanged receipt clears nothing. A scripted assent is not user text and never
    re-approves. Returns None for a pre-release contract."""
    if not epoch_two(rundir):
        return None
    missing = _run_init_errors(rundir, "approve_plan")
    if missing:
        raise ValueError(missing[0].message)
    root = Path(rundir)
    path = root / custody.CI1_RESPONSE
    text = quote if isinstance(quote, str) and quote.strip() and not scripted else None
    recorded = reapproved = False
    if path.exists() or path.is_symlink():
        raw = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        ours = raw is not None and custody.user_text_row(rundir, "checkin1_response", custody.CI1_RESPONSE,
                                                         _sha(raw)) is not None
        if not ours:
            _refuse_response(rundir, raw, "unrecorded_response_file")
        if text is not None and text.encode("utf-8") != raw:
            pin = custody.record_user_steering(rundir, text)
            custody.append(rundir, "steering", {"event": "approval", "user_text": pin,
                                                "approval_sha256": _approval_digest(rundir)})
            reapproved = True
        recorded = True
    elif text is not None:
        with path.open("xb") as stream:
            stream.write(text.encode("utf-8"))
        custody.record_user_text(rundir, "checkin1_response", custody.CI1_RESPONSE)
        custody.append(rundir, "steering", {"event": "approval", "user_text": {"path": custody.CI1_RESPONSE,
                                            "sha256": _sha(path.read_bytes())},
                                            "approval_sha256": _approval_digest(rundir)})
        recorded = True
    if not _events(rundir, "checkin1"):
        custody.record_input_snapshot(rundir, "checkin1")
    return {"response_recorded": recorded, "reapproval": reapproved, "checkin1": True}


def _locate(text, needles):
    for needle in needles:
        if needle and needle in text:
            start = text.index(needle)
            return start, start + len(needle), needle
    return None


def _committed_digest(rundir, case_id):
    lines = custody.rows(rundir, "journal-" + case_id)
    if not lines or lines[0]["record"]["event"] != "proposal_committed":
        raise ValueError(f"case {case_id} has no committed proposal in custody")
    return lines[0]["record"]["data"]["digest"]


def _reopenable(rundir, digest):
    """A reopen resets a per-action case budget; it names an action with an escalate receipt or a
    spent budget since the last reopen."""
    from .rdj_anchor import policy
    since = custody.last_reopen_ns(rundir, digest)
    cases = [r for r in custody.rows(rundir, "cases") if r["record"]["digest"] == digest and r["ns"] > since]
    ids = {r["record"]["case_id"] for r in cases}
    if any(r["record"]["case_id"] in ids and r["record"]["outcome"] == "escalate" for r in custody.rows(rundir, "receipts")):
        return True
    return len(cases) >= policy()["budgets"]["max_cases_per_action"]


def respond(rundir, text, *, approve=(), reopen=(), withdraw=()):
    """The trusted response path: record the user's text, then each decision the operator names.

    ``approve`` lists case ids, ``reopen`` action digests and ``withdraw`` ``(case_id, finding_id)``
    pairs. Every decision quotes the recorded text (the case id or the first 12 characters of the
    action digest, or the finding id); text that names none of them records no decision."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a response records the user's actual text")
    if not (approve or reopen or withdraw):
        raise ValueError("a response names at least one decision; a message without one is steering (ravel steer)")
    plans = []
    for case_id in approve:
        digest = _committed_digest(rundir, case_id)
        span = _locate(text, (case_id, digest[:12]))
        if span is None:
            raise ValueError(f"the response text names neither case {case_id} nor its action digest")
        plans.append(("approve", case_id, digest, span))
    for digest in reopen:
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("a reopen decision names the full action digest")
        if not _reopenable(rundir, digest):
            raise ValueError(f"action {digest[:12]} was not escalated and its case budget is not spent; nothing to reopen")
        span = _locate(text, (digest[:12],))
        if span is None:
            raise ValueError(f"the response text does not quote action {digest[:12]}")
        plans.append(("reopen", None, digest, span))
    for case_id, finding_id in withdraw:
        digest = _committed_digest(rundir, case_id)
        span = _locate(text, (finding_id,))
        if span is None:
            raise ValueError(f"the response text does not quote finding {finding_id}")
        plans.append(("withdraw", (case_id, finding_id), digest, span))
    pin = custody.record_user_steering(rundir, text)
    decisions = []
    for decision, subject, digest, (start, end, quoted) in plans:
        common = dict(source="user_steering", path=pin["path"], start=start, end=end, text=quoted)
        if decision == "approve":
            custody.record_human_approval(rundir, case_id=subject, **common)
            decisions.append({"decision": "approve", "case_id": subject, "action_digest": digest})
        elif decision == "reopen":
            custody.record_reopen(rundir, action_digest=digest, **common)
            decisions.append({"decision": "reopen", "action_digest": digest})
        else:
            custody.record_withdrawal(rundir, case_id=subject[0], finding_id=subject[1], **common)
            decisions.append({"decision": "withdraw", "case_id": subject[0], "finding_id": subject[1],
                              "action_digest": digest})
    return {"user_text": pin, "decisions": decisions}


# ---------------------------------------------------------------- steering

def _approved_inputs(rundir):
    root = Path(rundir)
    rels = [custody.TASK_CONTRACT, "inputs/checkin1.json", "inputs/checkin1_approval.json"]
    plan = (_contract(rundir) or {}).get("request_plan")
    if isinstance(plan, dict) and isinstance(plan.get("path"), str):
        rels.append(plan["path"])
    return {rel: _sha((root / rel).read_bytes()) for rel in rels if (root / rel).is_file()}


@contextmanager
def _steering_lock(rundir):
    directory = custody.root(rundir)
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory / 'steering-dispatch.lock'):
        yield


def _steering_epoch(rows):
    return sum(r['record'].get('event') in ('steering', 'approval') for r in rows)


def _authority(authority):
    # Same-user CLI text cannot attest a human identity.
    if authority not in ('unknown', 'delegated_machine', 'scripted_experiment'):
        raise ValueError('authority requires authenticated evidence for a human label; use unknown for same-user text')
    return authority


def _test_lock_domain():
    from . import machine_lease
    return machine_lease.domain() == 'test'


def _mirror_names(rundir):
    directory = Path(rundir) / STEERING_RECORDS
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def _administrative_only(rundir):
    """True when the location holds nothing but steering text and mirrors (or does not exist)."""
    root = Path(rundir)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        return False
    allowed = (STEERING_RECORDS + '/', custody.STEERING_DIR + '/')
    return all(not p.is_symlink() and (p.relative_to(root).as_posix() in ('inputs', STEERING_RECORDS, custody.STEERING_DIR)
                                       or p.relative_to(root).as_posix().startswith(allowed))
               for p in (root.rglob('*') if root.is_dir() else ()))


def _steering_journal(rundir, *, required=True):
    """The run's verified steering rows; custody decides, mirrors never do.

    A mirror in ``inputs/steering`` without the custody row it mirrors means custody was lost (a
    renamed or copied run directory) and is refused. With ``required``, a location custody never
    initialized is refused as well: dispatch needs an initialization or binding record
    (``initialize_steering``, a run_init snapshot, a parent binding or an earlier steering row),
    so an empty journal RAVEL created is distinct from absent custody. Only the test lock
    domain serves a location that was never initialized, as it serves a lease without a binding.
    """
    rows = custody.rows(rundir, 'steering')
    events = {r['record'].get('event') for r in rows}
    for name in _mirror_names(rundir):
        if ('parent_binding' if name == PARENT_MIRROR else 'steering') not in events:
            raise custody.CustodyError('steering mirrors exist but steering custody is missing; reconcile the run location')
    if required and not rows and not _test_lock_domain() and not _events(rundir, 'run_init'):
        raise custody.CustodyError(
            'steering custody is absent for this run location: no initialization or binding record exists. '
            'A renamed or copied run is served only at its recorded location; for a new run directory the '
            f'operator records it with `{JOURNAL_INIT_COMMAND}`')
    return rows


# The documents that state what a run is. A directory without an identity record is recognized by them.
RUN_DOCUMENTS = (custody.TASK_CONTRACT, 'inputs/science-plan.json', 'graph_spec.json')
# A transport qualification directory must stay empty until its probe passes (a refusal before
# any process leaves nothing behind), so it gets its journal and no identity record.
RECORDLESS_ROUTES = ('transport-qualification',)


def _documents(rundir):
    """The sha256 of each run document the directory holds now."""
    found = {}
    for rel in RUN_DOCUMENTS:
        path = Path(rundir) / rel
        try:
            if path.is_file() and not path.is_symlink():
                found[rel] = _sha(path.read_bytes())
        except (OSError, ValueError):
            continue
    return found


def _location(rundir):
    """Where a run is, which identity it carries and what states it, recorded with its custody rows
    so that a later copy or rename of the directory is recognized as this run."""
    try:
        identity = custody.run_identity(rundir)
    except (custody.CustodyError, OSError):
        identity = None  # An unreadable record never blocks a steering row; initialization refuses it.
    return {'path': str(Path(rundir).resolve()), 'run_id': identity, 'documents': _documents(rundir)}


def _steering_texts(rundir):
    """``(path, sha256)`` of each steering text file in the directory (``inputs/user-steering``)."""
    root = Path(rundir)
    directory = root / custody.STEERING_DIR
    texts = set()
    if directory.is_dir() and not directory.is_symlink():
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.is_symlink():
                texts.add((path.relative_to(root).as_posix(), _sha(path.read_bytes())))
    return texts


def _recorded_runs():
    """What custody on this machine records about each run: where it is served, the documents that
    have stated it, the steering text recorded for it and its parent binding.

    Read from every run's own ledgers, so custody written before locations were recorded is
    included with what it holds: a journal row's path, a parent's binding row for a child, the
    input snapshots and the approved inputs of a steering event."""
    known, children = {}, []
    for name, directory in custody.stores():
        steering = custody.store_rows(directory, 'steering')
        inputs = custody.store_rows(directory, 'inputs')
        if not steering and not inputs:
            continue
        run = known[name] = {'store': name, 'paths': [], 'documents': {}, 'texts': set(), 'parent': None}

        def note(rel, digest, run=run):
            if rel in RUN_DOCUMENTS and isinstance(digest, str):
                run['documents'].setdefault(rel, set()).add(digest)
        for row in steering:
            record = row['record']
            event = record.get('event')
            location = record.get('location') if isinstance(record.get('location'), dict) else {}
            path = location.get('path') or (record.get('path') if event == 'journal_init' else None)
            if isinstance(path, str) and path not in run['paths']:
                run['paths'].append(path)
            documents = location.get('documents')
            for rel, digest in (documents.items() if isinstance(documents, dict) else ()):
                note(rel, digest)
            if event == 'steering':
                approved = (record.get('record') or {}).get('approved_inputs')
                for rel, digest in (approved.items() if isinstance(approved, dict) else ()):
                    note(rel, digest)
            elif event == 'parent_binding':
                run['parent'] = record.get('path')
            elif event == 'child_binding' and isinstance(record.get('path'), str):
                children.append(record['path'])
        for row in inputs:
            files = row['record'].get('files')
            for rel in (RUN_DOCUMENTS if isinstance(files, dict) else ()):
                note(rel, files.get(rel))
        for row in custody.store_rows(directory, 'user_text'):
            if row['record'].get('source') == 'user_steering':
                run['texts'].add((row['record'].get('path'), row['record'].get('sha256')))

    def served_at(path):
        try:
            return custody.root(path).name
        except (custody.CustodyError, OSError, ValueError, RuntimeError):
            return None
    # A child bound before its own location was recorded is located through its parent's row.
    for path in children:
        run = known.get(served_at(path))
        if run is not None and path not in run['paths']:
            run['paths'].append(path)
    # The documents each run has now, read where custody serves it.
    for run in known.values():
        for path in run['paths']:
            if served_at(path) == run['store']:
                for rel, digest in _documents(path).items():
                    run['documents'].setdefault(rel, set()).add(digest)
    return list(known.values())


def _recorded_elsewhere(basis, where, parent=None):
    where = where or 'a location its custody does not name'
    bound = f' It is bound to the study at {parent}, whose steering governs it.' if parent else ''
    return custody.CustodyError(
        f'steering custody for this run already exists at another location ({where}): this directory has '
        f'{basis} and no steering record of its own, so it is a renamed or copied run, not a new one.{bound} '
        'Nothing was initialized; every pause, veto and binding recorded there stays in force. A run is '
        f'served only at its recorded location: return the directory to {where}, or work there. (A run '
        'whose task contract names a bound run_id is moved with rdj_custody.relocate.)')


def _reconcile_identified(rundir, identity):
    """A directory that carries a run identity gets a journal only where custody bound that identity."""
    here = Path(rundir).resolve()
    recorded = custody.location(identity)
    if recorded == str(here):
        return
    if recorded is None:
        if sorted(p.name for p in here.iterdir()) == [custody.RUN_IDENTITY]:
            custody.bind_run(here, identity)  # creation was interrupted between the record and its binding
            return
        raise custody.CustodyError(
            'this directory carries a run identity that custody on this machine never bound: its steering '
            'custody is elsewhere or was lost. Nothing was initialized; a run is served only where its '
            'custody is')
    raise _recorded_elsewhere('the identity of the run recorded there', recorded)


def _reconcile_unidentified(rundir):
    """Refuse to start a journal for a directory that custody already knows at another location.

    A directory without an identity record is the same run as one custody knows when it holds the
    same task contract (for a study or a graph without one, the same plan or graph specification),
    or steering text that was recorded for that run. Missing mirrors never make a directory new."""
    if not Path(rundir).is_dir():
        return
    here = custody.root(rundir).name
    documents = _documents(rundir)
    primary = next((rel for rel in RUN_DOCUMENTS if rel in documents), None)
    # Steering text custody recorded at this location belongs here; any other was recorded elsewhere.
    texts = _steering_texts(rundir) - {(r['record'].get('path'), r['record'].get('sha256'))
                                        for r in custody.rows(rundir, 'user_text')}
    if primary is None and not texts:
        return  # Nothing in the directory states a run: there is nothing custody could know it by.
    recorded = [run for run in _recorded_runs() if run['store'] != here]
    for run in recorded:
        if primary is not None and documents[primary] in run['documents'].get(primary, ()):
            label = 'the same task contract' if primary == custody.TASK_CONTRACT else f'the same {primary}'
            raise _recorded_elsewhere(label, run['paths'][-1] if run['paths'] else None, run['parent'])
    if texts:
        # Steering text exists in a directory only where custody recorded it.
        run = next((run for run in recorded if texts & run['texts']), None)
        raise _recorded_elsewhere('steering text that custody recorded for it',
                                  run['paths'][-1] if run and run['paths'] else None, run and run['parent'])


def initialize_steering(rundir, *, route):
    """Record that the steering journal of this run location exists; idempotent.

    Called where RAVEL creates a run, study, scan, graph scope or qualification directory, and by
    the operator (``steer init``) for a directory prepared by hand. A location that already has
    steering custody keeps it. Mirrors without custody are refused: a moved run is never given a
    new journal.

    Absent mirrors do not make a directory new either. Before a journal is started the directory
    is reconciled with the custody that already exists on this machine: one that carries the
    identity of a run bound elsewhere, or (without an identity) the task contract or the recorded
    steering text of a run custody knows at another location, is that run renamed or copied, and
    is refused. A directory that passes gets its identity record and binding here
    (``rdj_custody.bind_new_run``), so later copies of it are recognized by identity; a
    transport qualification directory is the exception and is left as it is."""
    if route not in JOURNAL_ROUTES:
        raise ValueError(f'steering journal route must be one of {JOURNAL_ROUTES}')
    with _steering_lock(rundir):
        rows = _steering_journal(rundir, required=False)
        if rows:
            return next((r['record'] for r in rows if r['record'].get('event') == 'journal_init'), None)
        # One journal is started at a time on this machine, so two copies of one run are never
        # both reconciled against a custody that knows neither of them yet.
        with file_lock(custody.root(rundir).parent / 'steering-init.lock'):
            identity = custody.run_identity(rundir)
            if identity is not None:
                _reconcile_identified(rundir, identity)
            else:
                _reconcile_unidentified(rundir)
                if route not in RECORDLESS_ROUTES:
                    _bind_identity(rundir)
            record = {'event': 'journal_init', 'route': route, 'path': str(Path(rundir).resolve()),
                      'location': _location(rundir)}
            custody.append(rundir, 'steering', record)
            return record


def _bind_identity(rundir):
    """Write and bind the identity record of a directory that has none (an existing real directory)."""
    root = Path(rundir)
    if root.is_dir() and not root.is_symlink() and custody.run_identity(root) is None:
        return custody.bind_new_run(root)
    return None


def record_steering(rundir, text, *, effect, affected_nodes=(), span=None,
                    authority='unknown', scope_increase=None, supersedes=None,
                    priority=0, expected_epoch=None, policy=None, disposition=None):
    """Extend the custody steering journal; readable mirrors never grant authority.

    Redirects require reapproval unless explicitly declared within scope. Requirements
    and redirects require a content-pinned amended plan in their acknowledgement.
    """
    if effect not in STEERING_EFFECTS:
        raise ValueError(f'steering effect must be one of {STEERING_EFFECTS}')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('steering text is required')
    authority = _authority(authority)
    nodes = list(affected_nodes)
    if not all(isinstance(n, str) and n for n in nodes):
        raise ValueError('affected nodes are plan node ids')
    if type(priority) is not int:
        raise ValueError('priority is an integer')
    if scope_increase is not None and type(scope_increase) is not bool:
        raise ValueError('scope_increase is a boolean')
    start, end = (0, len(text)) if span is None else span
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(text)):
        raise ValueError('the steering span lies outside the text')
    with _steering_lock(rundir):
        # Steering before a run exists starts its journal; a directory that already holds run
        # content needs its initialization record first.
        rows = _steering_journal(rundir, required=not _administrative_only(rundir))
        epoch = _steering_epoch(rows)
        if expected_epoch is not None and expected_epoch != epoch:
            raise ValueError('stale steering response: epoch changed')
        if supersedes is not None:
            previous = next((r['record']['record'] for r in rows if r['record'].get('event') == 'steering'
                             and r['record']['record'].get('event_id') == supersedes), None)
            if previous is None or previous['effect'] != 'veto' or effect != 'resume':
                raise ValueError('resume may supersede an existing veto only')
            nodes = list(previous['affected_nodes'])
        # A declared scope increase needs plan reapproval whatever its effect; an acknowledgement never grants it.
        requires = (effect == 'scope_change' or scope_increase is True
                    or (effect == 'redirect' and scope_increase is not False) or policy is not None)
        # Every plan read precedes the first custody write: an unreadable plan records nothing.
        descendants = None
        if nodes or requires:
            try:
                plan_nodes, plan_edges = _plan_graph(rundir)
            except PlanUnreadable as exc:
                raise PlanUnreadable(f'{exc}; nothing was recorded. Repair the plan, or address the whole '
                                     'study (no affected nodes) with a pause or a veto') from None
            if nodes:
                descendants = sorted(n['id'] for n in plan_nodes if set(nodes) & _ancestors(plan_edges, n['id']))
        pin = custody.record_user_steering(rundir, text)
        record = {'schema_version': 1, 'kind': 'user-steering-record',
                  'user_text': {'source': 'user_steering', 'path': pin['path'], 'sha256': pin['sha256']},
                  'span': {'start': start, 'end': end, 'text': text[start:end]},
                  'source_text': text, 'effect': effect, 'affected_nodes': nodes,
                  'requires_reapproval': requires, 'decides': False, 'authority': authority,
                  'recorded_utc': _utc(), 'priority': priority, 'supersedes': supersedes}
        if descendants is not None:
            record['affected_descendants'] = descendants
        if effect == 'resume' and supersedes is None:
            pauses = [r['record']['record'] for r in rows if r['record'].get('event') == 'steering'
                      and r['record']['record']['effect'] == 'pause']
            record['resumes'] = pauses[-1]['event_id'] if pauses else None
        if requires:
            record['approved_inputs'] = _approved_inputs(rundir)
            record['approval_sha256_at_event'] = _approval_digest(rundir)
            record['reapproval_steps'] = sorted(_reapproval_steps(rundir, record))
            # After an approval, only the delegation already in force may reapprove;
            # a policy change cannot authorize its own machine reapproval.
            prior = _current_policy(rows)
            record['reapproval_policy'] = prior if record['approval_sha256_at_event'] is not None else (policy or prior)
        if policy is not None:
            record['policy'] = policy
        if disposition is not None:
            record.update(disposition=disposition, scientific_acceptance=False)
        def number(existing):
            record['n'] = 1 + sum(r['record'].get('event') == 'steering' for r in existing)
            record['epoch'] = _steering_epoch(existing) + 1
            record['event_id'] = f"steering-{record['epoch']}"
        custody.append(rundir, 'steering', {'event': 'steering', 'record': record, 'location': _location(rundir)},
                       check=number)
        directory = Path(rundir) / STEERING_RECORDS
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record['n']:04d}.json"
        atomic_json(path, record)
        if policy is not None:
            atomic_json(directory / 'policy.json', policy)
        if effect == 'pause':
            # Commit the dispatch refusal before asking execution backends to stop.
            from . import graph_substrate, agent_worker
            cancel = ((policy or _current_policy(rows) or {}).get('on_pause', 'drain') == 'cancel')
            errors = []
            markers = _pause_markers(rundir, rows)
            pause = record['event_id']
            # The intent, with what each stop marker replaces, is durable before any marker is
            # written, and every marker names this pause: a resume after a crash anywhere below
            # restores exactly the markers this pause wrote.
            custody.append(rundir, 'steering', {'event': 'pause_intent', 'event_id': pause,
                                               'mode': 'cancel' if cancel else 'drain', 'markers': markers})
            for label, stop in (
                ('graph', lambda: [graph_substrate.stop(scope, reason=text, now=cancel, pause=pause)
                                   for scope in _execution_scopes(rundir)]),
                ('worker', lambda: [agent_worker.stop(scope, drain=not cancel, pause=pause)
                                    for scope in _execution_scopes(rundir) if scope.name != 'effects'])):
                try:
                    stop()
                except (OSError, ValueError) as exc:
                    errors.append(f'{label}: {exc}')
            custody.append(rundir, 'steering', {'event': 'pause_execution', 'event_id': record['event_id'],
                                               'errors': errors, 'mode': 'cancel' if cancel else 'drain',
                                               'stop_markers': _pin_pause_markers(rundir, markers)})
        return {**record, 'path': path.relative_to(Path(rundir)).as_posix()}


def _current_policy(rows):
    policies = [r['record']['record']['policy'] for r in rows
                if r['record'].get('event') == 'steering' and 'policy' in r['record']['record']]
    return policies[-1] if policies else None


def set_steering_policy(rundir, policy, *, source_text, authority='unknown', expected_epoch=None):
    """Retain the exact policy source text and validated fields in custody."""
    if not isinstance(policy, dict):
        raise ValueError('policy must be an object')
    if set(policy) - {'autonomy', 'checkin_thresholds', 'hard_ceilings', 'signoff_steps', 'unknown_cost', 'on_pause', 'result_acceptance', 'authority', 'source_text'}:
        raise ValueError('unknown steering policy field')
    choices = {'autonomy': ('manual', 'bounded_delegated'), 'unknown_cost': ('ask', 'pilot_first'),
               'on_pause': ('drain', 'cancel'), 'result_acceptance': ('physicist', 'review_only')}
    for key, allowed in choices.items():
        if policy.get(key) not in allowed:
            raise ValueError(f'policy {key} must be one of {allowed}')
    keys = ('cpu_hours', 'wall_hours', 'disk_gb', 'events', 'model_calls')
    value = {k: policy[k] for k in choices}
    for name in ('checkin_thresholds', 'hard_ceilings'):
        vector = policy.get(name)
        if not isinstance(vector, dict) or set(vector) - set(keys):
            raise ValueError(f'policy {name} must contain resource ceilings')
        for item in vector.values():
            if item is not None and (type(item) not in (int, float) or not math.isfinite(item) or item < 0):
                raise ValueError(f'policy {name} needs nonnegative finite numbers or null')
        value[name] = {k: vector.get(k) for k in keys}
    steps = policy.get('signoff_steps')
    if not isinstance(steps, list) or any(not isinstance(s, str) or not s for s in steps):
        raise ValueError('policy signoff_steps is a list of operation or rung ids')
    value.update(signoff_steps=steps, source_text=source_text, authority=_authority(authority))
    event = record_steering(rundir, source_text, effect='requirement', authority=authority,
                            policy=value, expected_epoch=expected_epoch)
    present_steering_policy(rundir)
    return event


def steering_policy(rundir):
    """The custody policy to present for a run, or None. Presentation only: a location without
    steering custody has no policy to show, and dispatch there is refused separately."""
    return _current_policy(_steering_journal(_steering_owner(rundir), required=False))


def present_steering_policy(rundir):
    """Present custody policy in the ordinary administrative CHECK-IN artifacts."""
    path = Path(rundir) / 'inputs/checkin1.json'
    policy = steering_policy(rundir)
    if policy is None or not path.is_file():
        return
    checkin = json.loads(path.read_text())
    checkin.setdefault('sections', {})['steering_policy'] = policy
    atomic_json(path, checkin)
    markdown = Path(rundir) / 'CHECKIN1.md'
    if markdown.is_file():
        start, end = '<!-- steering-policy -->', '<!-- /steering-policy -->'
        text = markdown.read_text()
        if start in text and end in text:
            before, rest = text.split(start, 1)
            text = before + rest.split(end, 1)[1]
        markdown.write_text(text.rstrip() + '\n\n' + start + '\n' + render_steering_policy(rundir)
                            + '\n' + end + '\n')


def record_plan_approval(rundir, *, authority='unknown'):
    """Called by the existing plan approval writer after it emits its receipt."""
    authority = _authority(authority)
    with _steering_lock(rundir):
        return _record_plan_approval_locked(rundir, authority)


def _record_plan_approval_locked(rundir, authority, *, superseded=None, details=None):
    """Validate and record the current receipt's approval; the caller holds the steering lock.

    ``superseded`` (the replaced receipt's digest and archive) is recorded only after the approval
    has been validated, so a refusal appends nothing."""
    rows = _steering_journal(rundir, required=False)
    if not any(r['record'].get('event') == 'steering' for r in rows):
        return None
    digest = _approval_digest(rundir)
    if digest is None:
        raise ValueError('plan approval receipt is absent')
    for row in rows:
        event = row['record'].get('record', {})
        if row['record'].get('event') != 'steering' or not event.get('requires_reapproval'):
            continue
        if _reapproved(rundir, rows, row, digest):
            continue
        if 'approval_sha256_at_event' not in event or digest == event['approval_sha256_at_event']:
            raise ValueError('plan approval receipt is unchanged or its event baseline is missing')
        if not _reapproval_authority_permitted(rundir, rows, event, authority):
            raise ValueError('plan approval authority cannot reapprove this steering scope; operator signoff is required')
    if superseded is not None:
        custody.append(rundir, 'steering', {'event': 'approval_superseded', 'approval_sha256': superseded[0],
                                           'archive': superseded[1]})
    elif rows and rows[-1]['record'].get('event') == 'approval' and rows[-1]['record'].get('approval_sha256') == digest:
        return rows[-1]['record']
    record = {'event': 'approval', 'approval_sha256': digest, 'authority': authority, **(details or {})}
    custody.append(rundir, 'steering', record)
    return record


def _plan_approval_refusal(rundir, rows, authority):
    for row in rows:
        event = row['record'].get('record', {})
        if row['record'].get('event') == 'steering' and event.get('requires_reapproval') \
                and not _reapproval_authority_permitted(rundir, rows, event, authority):
            return 'plan approval authority cannot reapprove this steering scope; operator signoff is required'
    return None


def plan_approval_refusal(rundir, authority='unknown'):
    """Why a plan approval receipt written now under ``authority`` would not be recorded, or None.

    An approval writer calls this before it writes: a receipt that ``record_plan_approval`` would
    refuse is never left in the run. Every steering event that needs reapproval must permit the
    authority, because a new receipt is reconciled against all of them. It is a preliminary
    answer; ``plan_approval_transaction`` decides again under the steering lock."""
    authority = _authority(authority)
    return _plan_approval_refusal(rundir, _steering_journal(rundir, required=False), authority)


@contextmanager
def plan_approval_transaction(rundir, receipt_path, *, authority='unknown', details=None):
    """One steering transaction for a plan approval writer.

    Under the steering lock: the final authority check, then the writer's block (it checks the
    presented policy, archives the receipt it replaces and writes the new one), then the
    registration. A refusal or failure anywhere restores the previous current receipt (removes a
    first one), removes what the block created and appends nothing to custody. The block sets
    ``transaction['superseded'] = (digest, archive)`` for a replaced receipt; the record lands in
    ``transaction['record']``. The lock is not re-entrant: the block must not call steering
    functions that take it."""
    authority = _authority(authority)
    path = Path(receipt_path)
    with _steering_lock(rundir):
        refusal = _plan_approval_refusal(rundir, _steering_journal(rundir, required=False), authority)
        if refusal:
            raise ValueError(refusal)
        previous = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        transaction = {'superseded': None, 'created': [], 'record': None}
        try:
            yield transaction
            transaction['record'] = _record_plan_approval_locked(
                rundir, authority, superseded=transaction['superseded'], details=details)
        except BaseException:
            if previous is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != previous:
                _restore_bytes(path, previous)
            for created in transaction['created']:
                Path(created).unlink(missing_ok=True)
            raise


def _restore_bytes(path, raw):
    temporary = path.with_name(path.name + '.restore')
    with temporary.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


# What the steering policy does in this release. The other fields are the physicist's recorded
# instruction for planning and for the ordinary budget and review checks.
POLICY_ENFORCEMENT = ('Enforced by steering: autonomy, signoff_steps, on_pause.\n'
                      'Recorded for the plan, not enforced by steering: checkin_thresholds, hard_ceilings, '
                      'unknown_cost, result_acceptance. A ceiling recorded here does not by itself refuse a '
                      'launch; the approved plan and the ordinary budget checks do.')


def render_steering_policy(rundir):
    policy = steering_policy(rundir)
    if policy is None:
        return 'Steering policy: none recorded.'
    return ('Steering policy (authority: ' + policy['authority'] + ')\n\n' + policy['source_text'] + '\n\n'
            + json.dumps(policy, indent=2) + '\n\n' + POLICY_ENFORCEMENT)


def ack_steering(rundir, event_id, *, interpretation, amended_plan=None, expected_epoch=None):
    """Acknowledge current instructions without granting execution or scientific approval."""
    if not isinstance(interpretation, str) or not interpretation.strip():
        raise ValueError('acknowledgement interpretation is required')
    with _steering_lock(rundir):
        rows = custody.rows(rundir, 'steering')
        epoch = _steering_epoch(rows)
        if expected_epoch is not None and expected_epoch != epoch:
            raise ValueError('stale acknowledgement: epoch changed')
        event = next((r['record']['record'] for r in rows if r['record'].get('event') == 'steering'
                      and r['record']['record'].get('event_id', f"legacy-{r['record']['record']['n']}") == event_id), None)
        if event is None:
            raise ValueError('unknown steering event')
        if expected_epoch is None and any(
                r['record'].get('event') == 'steering' and r['record']['record'].get('n', 0) > event.get('n', 0)
                for r in rows):
            # A later instruction exists: the answer states the view it was written against.
            raise ValueError('newer steering was recorded after this event; read the current state and '
                             'acknowledge with --expected-epoch <epoch>')
        pin = None
        if amended_plan is not None:
            path = Path(amended_plan)
            path = path if path.is_absolute() else Path(rundir) / path
            path = path.resolve()
            rel = path.relative_to(Path(rundir).resolve()).as_posix()
            raw = path.read_bytes()
            if not isinstance(json.loads(raw), dict):
                raise ValueError('amended plan must be a JSON object')
            pin = {'path': rel, 'sha256': _sha(raw)}
        if event['effect'] in ('requirement', 'redirect', 'scope_change') and 'policy' not in event and pin is None:
            raise ValueError('requirement or redirect needs an amended plan to reconcile affected work')
        record = {'event': 'acknowledgement', 'event_id': event_id, 'epoch': epoch,
                  'interpretation': interpretation, 'amended_plan': pin, 'authority': 'delegated_machine',
                  'approves_scope': False}
        custody.append(rundir, 'steering', record)
        atomic_json(Path(rundir) / STEERING_RECORDS / f'{event_id}-ack.json', record)
        if event['effect'] == 'resume' and event.get('supersedes') is None:
            _clear_pause_markers(rundir, rows, event.get('resumes'))
        return record


def record_result_disposition(rundir, disposition, text, *, authority='unknown', expected_epoch=None):
    if disposition not in ('accept', 'reject', 'rework'):
        raise ValueError('result disposition must be accept, reject or rework')
    return record_steering(rundir, text, effect='result_disposition', disposition=disposition,
                           authority=authority, expected_epoch=expected_epoch)


def _steering_owner(rundir):
    root = Path(rundir)
    # The ordinary graph adapter places its execution substrate here.
    return root.parent if root.name == 'effects' and (root.parent / 'graph_spec.json').is_file() else root


def checkin_policy_section(context):
    root = context.get('base_dir')
    if root is None:
        return None
    return steering_policy(root)


class PlanUnreadable(ValueError):
    """The run's plan descriptor or plan structure cannot be read; dispatch and branch steering refuse."""


def _plan_graph(rundir):
    """The validated plan nodes and edges of a run: its request plan and its graph specification.

    A missing contract, descriptor or graph specification is no plan. A contract, descriptor, plan
    or graph specification that is present must be well formed: a launch never proceeds on a plan
    this function cannot read, whatever node it names.
    """
    root = Path(rundir)
    nodes, edges = [], []

    def refuse(message):
        raise PlanUnreadable('plan unreadable: ' + message)

    def document(path, label):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            refuse(f'{label} is not readable JSON ({type(exc).__name__})')
        if not isinstance(value, dict):
            refuse(f'{label} is not an object')
        return value

    def members(value, label):
        rows = value.get('nodes', [])
        if not isinstance(rows, list):
            refuse(f'{label} nodes is not a list')
        for node in rows:
            if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id']:
                refuse(f'{label} has a node without an id')
        return rows

    def endpoint(value, label):
        value = value.get('ref') if isinstance(value, dict) else value
        if not isinstance(value, str) or not value:
            refuse(f'{label} has an edge without two node references')
        return value

    contract_path = root / custody.TASK_CONTRACT
    if contract_path.is_symlink() or contract_path.exists():
        contract = document(contract_path, 'the task contract')
        # Only an absent key means the run has no request plan; null is a present, invalid descriptor.
        if 'request_plan' in contract:
            descriptor = contract['request_plan']
            if not isinstance(descriptor, dict) or not isinstance(descriptor.get('path'), str) or not descriptor['path']:
                refuse('the request plan descriptor names no plan path')
            try:
                path = (root / descriptor['path']).resolve()
                inside, present = path.is_relative_to(root.resolve()), path.is_file()
            except (OSError, RuntimeError, ValueError) as exc:
                # A symbolic-link loop, an unencodable name or a name the filesystem rejects.
                refuse(f'the request plan path cannot be resolved ({type(exc).__name__})')
            if not inside:
                refuse('the request plan lies outside the run')
            if not present:
                refuse('the request plan the contract names is absent')
            plan = document(path, 'the request plan')
            nodes.extend(members(plan, 'the request plan'))
            rows = plan.get('edges', [])
            if not isinstance(rows, list):
                refuse('the request plan edges is not a list')
            for edge in rows:
                if not isinstance(edge, dict):
                    refuse('the request plan has an edge that is not an object')
                edges.append((endpoint(edge.get('from'), 'the request plan'),
                              endpoint(edge.get('to'), 'the request plan')))
    graph = root / 'graph_spec.json'
    if graph.is_symlink() or graph.exists():
        rows = members(document(graph, 'the graph specification'), 'the graph specification')
        nodes.extend(rows)
        for node in rows:
            parents = node.get('depends_on', [])
            if not isinstance(parents, list) or any(not isinstance(dep, str) or not dep for dep in parents):
                refuse('the graph specification has a dependency that is not a node id')
            edges.extend((dep, node['id']) for dep in parents)
    return nodes, edges


def _ancestors(edges, node_id):
    ancestors = {node_id}
    while True:
        grown = ancestors | {source for source, target in edges if target in ancestors}
        if grown == ancestors:
            return ancestors
        ancestors = grown


def _stage_name(node):
    stage = node.get('stage')
    stage = stage.get('name') if isinstance(stage, dict) else stage
    return stage if isinstance(stage, str) and stage else None


def _owning_node(nodes, identity):
    """The plan node a launch identity belongs to: the node with that id or the node whose declared
    stage carries that name. None when the plan names no owner or more than one."""
    owners = {node['id'] for node in nodes if identity in (node['id'], _stage_name(node))}
    return next(iter(owners)) if len(owners) == 1 else None


def launch_node(rundir, stage, declared=None):
    """The plan node that owns a supervised stage, for the launch context.

    The plan decides: a node owns a stage when it carries that id or declares that stage name.
    ``declared`` (the node a production launch names) must agree with the plan; a stage the plan
    gives to another node is refused. None means the plan does not establish an owner, and
    dispatch then holds conservatively while any branch is blocked."""
    owner = _owning_node(_plan_graph(_steering_owner(rundir))[0], stage)
    if declared is not None and owner is not None and owner != declared:
        raise ValueError(f'stage {stage} belongs to plan node {owner}, not the declared plan node {declared}')
    return owner


def _node_ancestors(rundir, node_id):
    if node_id is None:
        return None
    return _ancestors(_plan_graph(rundir)[1], node_id)


def _plan_nodes(rundir):
    return _plan_graph(rundir)[0]


def _known_nodes(rundir):
    return {n['id'] for n in _plan_nodes(rundir)}


SCIENCE_PLAN = 'inputs/science-plan.json'  # science.PLAN
SCIENCE_RUNG = 'science'


def _science_steps(rundir):
    """The step identities of a scientific study plan: its stages, its operation (mode) and its rung."""
    path = Path(rundir) / SCIENCE_PLAN
    if not (path.is_symlink() or path.exists()):
        return set()
    try:
        plan = json.loads(path.read_text(encoding='utf-8'))
        stages = [stage['stage'] for stage in plan.get('stages', [])]
        mode = plan.get('mode')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PlanUnreadable(f'plan unreadable: the scientific study plan cannot be read ({type(exc).__name__})') from None
    if not all(isinstance(value, str) and value for value in stages) or (mode is not None and not isinstance(mode, str)):
        raise PlanUnreadable('plan unreadable: the scientific study plan names no stage or operation')
    return {SCIENCE_RUNG, *stages, *([mode] if mode else [])}


def _reapproval_steps(rundir, event):
    """Every node, operation and rung a reapproval of ``event`` covers, read from the current plan.

    The recorded descendants stay covered after a plan edit removes them, and a descendant the
    current plan adds below an affected node is covered as well. A scientific study has no
    request-plan graph; its stages, operation and rung are always covered.
    """
    nodes, edges = _plan_graph(rundir)
    named = set(event['affected_nodes'])
    affected = named | set(event.get('affected_descendants', []))
    affected |= {node['id'] for node in nodes if named & _ancestors(edges, node['id'])}
    steps = set(affected)
    for node in nodes:
        if not named or node['id'] in affected:
            steps.update(value for value in (node['id'], node.get('operation'), node.get('rung'))
                         if isinstance(value, str) and value)
    return steps | _science_steps(rundir)


def _execution_scopes(rundir):
    roots = [Path(rundir)]
    if (Path(rundir) / 'effects').is_dir():
        roots.append(Path(rundir) / 'effects')
    for row in custody.rows(rundir, 'steering'):
        if row['record'].get('event') == 'child_binding':
            child = Path(row['record']['path'])
            roots.append(child)
            if (child / 'effects').is_dir():
                roots.append(child / 'effects')
    return list(dict.fromkeys(roots))


def _marker_path(rundir, marker):
    scope = Path(marker['scope'])
    scope = scope if scope.is_absolute() else Path(rundir) / scope
    return scope / marker['path']


def _written_by(raw, pause_id):
    """True when the stop marker bytes ``raw`` were written by the steering pause ``pause_id``."""
    try:
        value = json.loads(raw)
    except ValueError:
        return False
    return type(value) is dict and value.get('steering_pause') == pause_id


def _pause_markers(rundir, rows):
    from . import graph_substrate
    prior = [m for r in rows if r['record'].get('event') == 'pause_execution'
             for m in r['record'].get('stop_markers', [])]
    intents = [r['record'] for r in rows if r['record'].get('event') == 'pause_intent']
    markers = []
    for scope in _execution_scopes(rundir):
        resolved = scope.resolve()
        base = Path(rundir).resolve()
        location = resolved.relative_to(base).as_posix() if resolved.is_relative_to(base) else str(resolved)
        for rel in (graph_substrate.STOP, 'agent-work/stop.json'):
            path = scope / rel
            raw = path.read_bytes() if path.is_file() else None
            previous = json.loads(raw) if raw else None
            # Repeated steering pauses retain the stop that preceded the first pause.
            old = next((m for m in reversed(prior) if m['scope'] == location and m['path'] == rel
                        and raw is not None and m['sha256'] == _sha(raw)), None)
            if old is None and raw is not None:
                # A marker an earlier pause wrote before its execution was recorded (a crash).
                old = next((m for intent in reversed(intents) for m in intent['markers']
                            if m['scope'] == location and m['path'] == rel
                            and _written_by(raw, intent['event_id'])), None)
            if old is not None:
                previous = old['previous']
            markers.append({'scope': location, 'path': rel, 'previous': previous})
    return markers


def _pin_pause_markers(rundir, markers):
    pinned = []
    for marker in markers:
        path = _marker_path(rundir, marker)
        if path.is_file():
            pinned.append({**marker, 'sha256': _sha(path.read_bytes())})
    return pinned


def _clear_pause_markers(rundir, rows, pause_id):
    execution = next((r['record'] for r in reversed(rows) if r['record'].get('event') == 'pause_execution'
                      and r['record']['event_id'] == pause_id), None)
    if execution is not None:
        # The execution pinned each marker it left: only those exact bytes are this pause's.
        owned = [(m, lambda raw, m=m: _sha(raw) == m['sha256']) for m in execution.get('stop_markers', [])]
    else:
        # The pause did not record its execution (a crash after its intent): a marker is this
        # pause's when it names the pause; one it never wrote, or a later stop, is not.
        intent = next((r['record'] for r in reversed(rows) if r['record'].get('event') == 'pause_intent'
                       and r['record']['event_id'] == pause_id), None)
        owned = [(m, lambda raw: _written_by(raw, pause_id)) for m in (intent or {}).get('markers', [])]
    for marker, mine in owned:
        path = _marker_path(rundir, marker)
        if not path.is_file() or not mine(path.read_bytes()):
            continue  # A later independent stop stays in force.
        if marker['previous'] is None:
            path.unlink()
        else:
            atomic_json(path, marker['previous'])


def bind_steering_child(rundir, child, node_id):
    """Bind ordinary research child dispatch to the parent's live steering authority.

    The binding is custody on both sides. The child also carries a readable mirror, so a child
    directory that was renamed or copied (its custody stays keyed to the bound location) is refused
    instead of being served as an unbound run."""
    with _steering_lock(rundir):
        _steering_journal(child, required=False)  # a child whose custody was lost is never rebound in place
        identity = custody.run_identity(child)
        if identity is not None:
            _reconcile_identified(child, identity)  # nor is a renamed or copied child bound again as a new one
        else:
            _bind_identity(child)  # the child is recognized by identity after a rename or a copy
        binding = {'event': 'parent_binding', 'path': str(Path(rundir).resolve()), 'node_id': node_id,
                   'location': _location(child)}
        custody.append(child, 'steering', binding)
        custody.append(rundir, 'steering', {'event': 'child_binding', 'path': str(Path(child).resolve()), 'node_id': node_id})
        directory = Path(child) / STEERING_RECORDS
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(directory / PARENT_MIRROR, {'schema_version': 1, 'kind': 'steering-parent-binding',
                                                'parent': binding['path'], 'node_id': node_id,
                                                'grants_authority': False})


def _steering_parent(rundir):
    rows = [r['record'] for r in custody.rows(rundir, 'steering') if r['record'].get('event') == 'parent_binding']
    return rows[-1] if rows else None


def _ack_current(rundir, ack):
    pin = ack.get('amended_plan')
    if pin is None:
        return True
    path = Path(rundir) / pin['path']
    return path.is_file() and _sha(path.read_bytes()) == pin['sha256']


def _reapproval_authority_permitted(rundir, rows, event, authority):
    if authority == 'unknown':
        return True  # Same-user operator text, without a human identity claim.
    if authority not in ('delegated_machine', 'scripted_experiment'):
        return False
    steps = set(event.get('reapproval_steps', [])) | _reapproval_steps(rundir, event)
    # A later policy cannot enlarge the delegation in force at the event.
    policies = (event.get('reapproval_policy'), _current_policy(rows))
    return all(policy is not None and policy.get('autonomy') == 'bounded_delegated'
               and not steps.intersection(policy.get('signoff_steps', [])) for policy in policies)


def _reapproved(rundir, rows, row, current):
    event = row['record']['record']
    if current is None or 'approval_sha256_at_event' not in event or current == event['approval_sha256_at_event']:
        return False
    return any(r['record'].get('event') == 'approval' and r['ns'] > row['ns']
               and r['record'].get('approval_sha256') == current
               and _reapproval_authority_permitted(rundir, rows, event, r['record'].get('authority', 'unknown'))
               for r in rows)


def steering_state(rundir):
    """Derive live state from verified custody; persist epochs across explicit relocation."""
    rundir = _steering_owner(rundir)
    rows = _steering_journal(rundir)
    events = [r for r in rows if r['record'].get('event') == 'steering']
    acks = {r['record']['event_id']: r['record'] for r in rows if r['record'].get('event') == 'acknowledgement'}
    superseded = {r['record']['record'].get('supersedes') for r in events
                  if r['record']['record'].get('event_id') in acks}
    paused, pause_requested, pause_id = False, False, None
    pending, vetoes, held = [], [], []
    current = _approval_digest(rundir)
    disposition = None
    for row in events:
        event = row['record']['record']
        identifier = event.get('event_id', f"legacy-{event['n']}")
        ack = acks.get(identifier)
        acknowledged = ack is not None and _ack_current(rundir, ack)
        if not acknowledged:
            pending.append(identifier)
        if event['effect'] == 'pause':
            paused = pause_requested = True
            pause_id = identifier
        elif event['effect'] == 'resume' and event.get('supersedes') is None and acknowledged:
            paused = pause_requested = False
        if event['effect'] == 'veto' and identifier not in superseded:
            vetoes.extend((event['affected_nodes'] + event.get('affected_descendants', [])) or ['*'])
        scope_hold = event.get('requires_reapproval') and not _reapproved(rundir, rows, row, current)
        ack_hold = not acknowledged and event['effect'] in ('requirement', 'redirect', 'scope_change', 'resume', 'priority')
        if scope_hold or ack_hold:
            held.extend((event['affected_nodes'] + event.get('affected_descendants', [])) or ['*'])
        if event['effect'] == 'result_disposition':
            disposition = dict(event)
    observed, stop_errors = False, []
    requested = pause_requested and not any(r['record'].get('event') == 'pause_execution' and r['record']['event_id'] == pause_id for r in rows)
    if pause_requested:
        from . import graph_substrate, agent_worker
        try:
            scopes = _execution_scopes(rundir)
            graphs = [graph_substrate.status(scope) for scope in scopes]
            workers = [p for scope in scopes if scope.name != 'effects' for p in agent_worker.processes(scope)]
            observed = (not requested and not any(admitted_work(scope) for scope in scopes)
                        and all(not graph.get('holder') and all(p.get('state') != 'running' for p in graph.get('processes', [])) for graph in graphs)
                        and all(p.get('status') == 'finished' and p.get('verified_gone') for p in workers))
        except (OSError, ValueError) as exc:
            stop_errors.append(str(exc))
        stop_errors.extend(e for r in rows if r['record'].get('event') == 'pause_execution'
                           and r['record']['event_id'] == pause_id for e in r['record']['errors'])
        if stop_errors:
            observed = False
    return {'epoch': _steering_epoch(rows), 'paused': paused, 'pending_ack': pending,
            'vetoed_nodes': sorted(set(vetoes)), 'held_nodes': sorted(set(held)), 'policy': _current_policy(rows),
            'pause_requested': pause_requested, 'observed_stopped': observed,
            'pause_status': 'requested' if requested else 'observed-stopped' if observed else 'draining' if pause_requested else 'running',
            'stop_errors': stop_errors, 'result_disposition': disposition}


def dispatch_permitted(rundir, node_id, *, _seen=()):
    """Steering permission only: existing admission and budgets still apply."""
    try:
        rundir = _steering_owner(rundir)
        resolved = str(Path(rundir).resolve())
        if resolved in _seen:
            return False, 'steering parent binding contains a cycle'
        parent = _steering_parent(rundir)
        if parent is not None:
            if not Path(parent['path']).is_dir():
                return False, 'steering parent is unavailable; reconcile its relocation'
            allowed, reason = dispatch_permitted(parent['path'], parent['node_id'], _seen=(*_seen, resolved))
            if not allowed:
                return False, 'parent steering: ' + reason
        state = steering_state(rundir)
        nodes, edges = _plan_graph(rundir)
        # A stage name resolves to the plan node that declares it; an identity the plan gives no
        # single owner keeps the conservative hold below.
        owner = node_id if not nodes else _owning_node(nodes, node_id)
        ancestors = _ancestors(edges, owner) if node_id is not None and owner is not None else None
    except PlanUnreadable as exc:
        return False, str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return False, f'steering custody or plan unreadable: {exc}'
    if state['paused']:
        return False, 'study is paused; new dispatch is refused'
    for key, reason in (('vetoed_nodes', 'node or ancestor is vetoed'),
                        ('held_nodes', 'affected work awaits acknowledgement, reconciliation or plan reapproval')):
        blocked = set(state[key])
        if blocked and (ancestors is None or '*' in blocked or blocked & ancestors):
            return False, reason
    return True, 'steering permits dispatch; ordinary approval and budget checks remain required'


@contextmanager
def steering_dispatch(rundir, node_id=None):
    """Serialize the final permission check and launch against steering changes."""
    rundir = _steering_owner(rundir)
    allowed, reason = dispatch_permitted(rundir, node_id)
    if not allowed:
        raise _launch_refusal(reason)
    parent = _steering_parent(rundir)
    with ExitStack() as stack:
        if parent is not None:
            stack.enter_context(steering_dispatch(parent['path'], parent['node_id']))
        stack.enter_context(_steering_lock(rundir))
        allowed, reason = dispatch_permitted(rundir, node_id)
        if not allowed:
            raise _launch_refusal(reason)
        yield


ADMITTED = 'steering-admitted.json'
ADMITTED_LOCKS = 'steering-admitted'
_ADMITTED_HERE = set()  # admissions whose body runs in this process


def _admitted_store(rundir):
    return custody.root(_steering_owner(rundir)) / ADMITTED


def _admission_lock(rundir, name):
    return _admitted_store(rundir).parent / ADMITTED_LOCKS / name


def _process_gone(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError, TypeError):
        return False
    return False


def _admission_ended(rundir, row):
    """True when the process that admitted this work no longer holds its admission lock.

    A process id alone does not identify running work: another process can carry it later, and a
    terminated process keeps it until it is reaped. Each admission therefore holds an exclusive
    lock on its own file for as long as its body runs. The kernel releases that lock when the
    process ends, however it ends, so a killed process, an unreaped one and a reused process id
    all read as ended. A record written before admissions held a lock names no lock and is
    judged by its process id, as it was."""
    import fcntl
    import os
    name = row.get('lock')
    if name is None:
        return _process_gone(row.get('pid'))
    if not isinstance(name, str) or not name or Path(name).name != name:
        return True  # A record that names anything but its own lock file identifies no running work.
    if row.get('id') in _ADMITTED_HERE and row.get('pid') == os.getpid():
        return False
    try:
        descriptor = os.open(_admission_lock(rundir, name), os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return True
    except OSError:
        return False  # The lock cannot be examined: the work is reported until it can be.
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False  # Held by the admitting process, or not examinable.
    finally:
        os.close(descriptor)
    return True


def _admitted_rows(rundir, path):
    """The records of work still running; ended records leave the file. Caller holds the record lock."""
    rows = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    running = [row for row in rows if not _admission_ended(rundir, row)]
    if running != rows:
        # Removed durably, under the admission-record lock, before the lock file of each goes.
        atomic_json(path, running)
        for row in rows:
            name = row.get('lock')
            if row not in running and isinstance(name, str) and name and Path(name).name == name:
                _admission_lock(rundir, name).unlink(missing_ok=True)
    return running


def admitted_work(rundir):
    """In-process work admitted under steering that has not ended: one record per running unit.

    The records live in custody, never in the run directory. Work whose process no longer holds
    its admission lock has ended with it: its record is removed here and is not listed."""
    path = _admitted_store(rundir)
    if not path.is_file():
        return []
    with file_lock(path.with_suffix('.lock')):
        return _admitted_rows(rundir, path)


def _admitted_change(rundir, *, add=None, remove=None):
    path = _admitted_store(rundir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix('.lock')):
        rows = [row for row in _admitted_rows(rundir, path) if row['id'] != remove]
        if add is not None:
            rows.append(add)
        atomic_json(path, rows)


@contextmanager
def steering_admitted(rundir, node_id=None, *, role='graph-node'):
    """Admit one unit of in-process work under the steering lock and keep it recorded while it runs.

    The final permission check and the record of running work are one steering transaction, so a
    pause that commits first refuses the work and a pause that commits afterwards finds it
    running. The lock is released before the body starts: the body drains under a later pause, is
    reported as running until it ends, and never blocks steering. The record is custody of the
    run that owns the steering; it names no process group, so a cancelling pause does not signal
    the process that runs the work, and nothing is written into the run directory. The record
    names the admission lock this process holds until the body ends, which is what identifies
    the work as running (``_admission_ended``)."""
    import fcntl
    import os
    import uuid
    identifier = f'steering-admitted-{os.getpid()}-{uuid.uuid4().hex[:12]}'
    name = identifier + '.lock'
    descriptor = None
    try:
        with steering_dispatch(rundir, node_id):
            lock = _admission_lock(rundir, name)
            lock.parent.mkdir(parents=True, exist_ok=True)
            # Held before the record exists: a record always names a lock its process took.
            descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _ADMITTED_HERE.add(identifier)
            _admitted_change(rundir, add={'id': identifier, 'pid': os.getpid(), 'lock': name, 'role': role,
                                          'node_id': node_id, 'scope': str(Path(rundir).resolve()),
                                          'started_utc': _utc()})
        try:
            yield identifier
        finally:
            _admitted_change(rundir, remove=identifier)
    finally:
        _ADMITTED_HERE.discard(identifier)
        if descriptor is not None:
            # The record is gone (or was never written); the lock file follows it.
            _admission_lock(rundir, name).unlink(missing_ok=True)
            os.close(descriptor)


def register_steering_process(rundir, process, context):
    """Register an owned session leader under the existing graph stop controller."""
    from . import graph_substrate
    graph_substrate._register_process(Path(rundir), {
        'id': f'steering-launch-{process.pid}', 'pid': process.pid, 'pgid': process.pid,
        'role': 'supervised-launch', 'state': 'running', 'started_utc': _utc(),
        'node_id': context.get('node_id'), 'stage': context.get('stage')})


def observe_steering_process(rundir, process):
    """Keep the stop view conservative until the registered group is observed gone."""
    from . import graph_substrate
    if not graph_substrate._group_alive(process.pid):
        graph_substrate._update_process(Path(rundir), f'steering-launch-{process.pid}',
                                        state='exited', ended_utc=_utc())


def prioritize_pending(rundir, rows):
    """Stable ranking of eligible pending work; never change resource eligibility."""
    priority = {}
    for event in steering_records(rundir):
        if event['effect'] == 'priority':
            for node in event['affected_nodes']:
                priority[node] = event['priority']
    return sorted(rows, key=lambda r: (not r.get('affordable', True),
                                      -priority.get(r.get('id', r.get('node_id')), 0)))

def _steering_rows(rundir):
    return [r for r in custody.rows(rundir, "steering") if r["record"].get("event") == "steering"]


def steering_records(rundir):
    """The steering records in custody, in order. The ``inputs/steering`` mirror is never read."""
    return [dict(r["record"]["record"]) for r in _steering_rows(rundir)]


def _verified_steering(rundir, record):
    """The record when its user text still verifies in custody and its span quotes that text."""
    binding = record.get("user_text") or {}
    whole, digest, _ = custody.user_text(rundir, "user_steering", binding.get("path"))
    span = record.get("span") or {}
    if digest != binding.get("sha256") or whole[span.get("start", 0):span.get("end", 0)] != span.get("text"):
        raise ValueError("the steering record does not quote its recorded user text")
    return record


def steering_anchor(rundir, n):
    """A ``user_requirement`` anchor citing the span of steering record ``n``."""
    record = next((r for r in steering_records(rundir) if r.get("n") == n), None)
    if record is None:
        raise ValueError(f"no steering record {n}")
    record = _verified_steering(rundir, record)
    span = record["span"]
    return {"kind": "user_requirement", "locator": "",
            "binding": {"source": "user_steering", "path": record["user_text"]["path"],
                        "sha256": record["user_text"]["sha256"], "start": span["start"], "end": span["end"],
                        "text": span["text"]}}


def steering_errors(rundir, gate="research_choice"):
    """A scope-change steering record holds until the operator re-approves: an ``approval`` row in
    the custody steering ledger, recorded after the steering row by the quoted approval path, whose
    approval digest is still the current ``inputs/checkin1_approval.json``. A byte change, an edit
    or a deletion of a run file never clears a hold."""
    errors = []
    rows = custody.rows(rundir, "steering")
    current = _approval_digest(rundir)
    for row in rows:
        if row["record"].get("event") != "steering" or not row["record"]["record"].get("requires_reapproval"):
            continue
        record = row["record"]["record"]
        if _reapproved(rundir, rows, row, current):
            continue
        errors.append(GateError("steering_requires_reapproval", gate, PROVIDER,
                                f"steering record {record.get('n')} changes scope ({', '.join(record.get('affected_nodes') or []) or 'plan'}); "
                                "the approved plan no longer covers the request",
                                "Amend the plan and obtain its CHECK-IN 1 re-approval (ravel approve --quote).",
                                ("custody:steering:" + str(record.get("n")),)))
    return errors


# ---------------------------------------------------------------- impossible fixtures and gaming events

def _store(name):
    from .execution_backend import state_dir
    return state_dir() / "gate-wiring" / name


def _read_lines(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_line(path, record):
    with file_lock(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def register_impossible_fixture(rundir, fixture_id, reason):
    """Declare (library callers only) that no honest path can pass this run's gates."""
    if not (isinstance(fixture_id, str) and fixture_id and isinstance(reason, str) and reason):
        raise ValueError("an impossible fixture names its id and reason")
    _append_line(_store("impossible.jsonl"), {"rundir": str(Path(rundir).resolve()), "fixture_id": fixture_id,
                                              "reason": reason, "utc": _utc()})


def impossible_fixture(rundir):
    run = str(Path(rundir).resolve())
    return next((r for r in reversed(_read_lines(_store("impossible.jsonl"))) if r["rundir"] == run), None)


def gaming_events(rundir):
    run = str(Path(rundir).resolve())
    return [r for r in _read_lines(_store("gaming-events.jsonl")) if r["rundir"] == run]


def _gaming(rundir, gate, action, fixture):
    record = {"rundir": str(Path(rundir).resolve()), "fixture_id": fixture["fixture_id"], "gate": gate,
              "action_digest": action.get("digest"), "action_kind": action.get("kind"), "utc": _utc()}
    _append_line(_store("gaming-events.jsonl"), record)
    return GateError("impossible_fixture_pass", gate, PROVIDER,
                     f"the gate passed on impossible fixture {fixture['fixture_id']}; recorded as a gaming event",
                     "Inspect the gaming event; an impossible fixture has no honest pass.",
                     ("gaming:" + fixture["fixture_id"],))


# ---------------------------------------------------------------- wired transitions

def _tripwire(rundir, gate, action, errors):
    if not errors:
        fixture = impossible_fixture(rundir)
        if fixture is not None:
            errors.append(_gaming(rundir, gate, action, fixture))
    return errors


def human_approval_errors(rundir, gate, action):
    """Same-user transport: an R3 gate also needs a recorded human approval of the case that
    authorizes ``action``, read from the receipt ``rdj_loop.authorizing_receipt`` returns. Without
    an authorizing receipt the ``rdj`` provider already refuses, so this adds nothing."""
    if gate not in R3_GATES or not SAME_USER_TRANSPORT:
        return []
    from . import rdj_loop
    accepted = rdj_loop.authorizing_receipt(Path(rundir), gate, action)
    if accepted is None or (accepted["receipt"].get("attestation_summary") or {}).get("human_approver"):
        return []
    case_id = accepted["case"]["case_id"]
    return [GateError("r3_human_approval_missing", gate, PROVIDER,
                      f"{gate} is R3 and its transport is same-user transport; case {case_id} has no recorded human approval",
                      f"The operator approves the case (ravel gate-wiring respond --approve {case_id}), then re-authorizes it.",
                      (f"rdj/cases/{case_id}.json",))]


def check_transition(rundir, gate, action):
    """``decision_gate.check`` at a wired transition, plus pending scope-change steering, the R3
    human approval under same-user transport and the impossible-fixture tripwire. Read-only
    except for the gaming event it records. A run without a contract is refused by the gate
    (``gate_inputs_invalid``); only an existing contract without the epoch key keeps its
    pre-release decision."""
    if gate not in WIRED_GATES:
        raise ValueError(f"unknown decision gate {gate}; wired gates: {WIRED_GATES}")
    from . import decision_gate
    errors = list(decision_gate.check(Path(rundir), gate, action))
    if epoch_two(rundir):
        errors += _run_init_errors(rundir, gate)
        if gate in STEERING_GATES:
            errors += steering_errors(rundir, gate)
        if not errors:
            errors += human_approval_errors(rundir, gate, action)
    return _tripwire(rundir, gate, action, errors)


def require_transition(rundir, gate, action):
    """Raise ``GateRefused`` unless the wired gate passes. The single entry every caller of a
    wired R0/R1 decision uses."""
    errors = check_transition(rundir, gate, action)
    if errors:
        raise GateRefused(gate, errors)


def _campaign_row(campaign, experiment):
    from . import research_cycle
    _, state = research_cycle._load(Path(campaign))
    row = next((e for e in state["experiments"] if e["id"] == experiment), None)
    if row is None:
        raise ValueError(f"campaign has no experiment {experiment}")
    return row


def require_research_choice(campaign, experiment):
    """The research_choice gate for adjudicating ``experiment`` of ``campaign``, decided on the
    experiment's run. Called before every ``research_cycle.adjudicate``."""
    row = _campaign_row(campaign, experiment)
    if row.get("rundir") is None:
        raise GateRefused("research_choice", [GateError(
            "gate_inputs_invalid", "research_choice", PROVIDER, f"experiment {experiment} has no run to decide on",
            "Prepare the experiment's run first.", ("campaign:" + str(experiment),))])
    rundir = row["rundir"]
    require_transition(rundir, "research_choice", research_choice_action(rundir, campaign, experiment, row))
    return row


def require_failed_feedback(rundir, intake_pin):
    """The failed_stage_feedback gate for feeding back the failed stage named by ``intake_pin``.
    Called before any diagnostic role runs and before any feedback is committed."""
    require_transition(rundir, "failed_stage_feedback", failed_feedback_action(rundir, intake_pin))


def value_action(rundir, kind, value, summary, *, write=False, node_id=None, floor=None):
    """An action over the canonical bytes of ``value`` at ``gate-actions/<kind>/<sha>.json``.

    ``write`` saves the bytes so a proposer can pin them when opening the RDJ case; a check
    recomputes the same digest without writing."""
    raw = _canonical(value)
    digest = _sha(raw)
    rel = f"{ACTIONS_DIR}/{kind}/{digest}.json"
    if write:
        path = Path(rundir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)
    action = {"kind": kind, "digest": digest, "summary": summary, "pins": [{"path": rel, "sha256": digest}],
              "node_id": node_id, "rung": None, "scope": None}
    if floor is not None:
        action["floor"] = floor
    return action


def failed_feedback_action(rundir, intake_pin, *, write=False):
    return value_action(rundir, "failed_stage_feedback", {"failed_stage_intake": dict(intake_pin)},
                        "Feed the failed stage's diagnostic intake back to its prospective cycle", write=write)


def research_choice_action(rundir, campaign, experiment, row, *, write=False):
    return value_action(rundir, "screening_choice",
                        {"campaign": str(campaign), "experiment": experiment, "row": row},
                        f"Adjudicate research experiment {experiment} and return its critique", write=write)


# ---------------------------------------------------------------- P15 delegated dispatch

def _rel_pins(rundir, pins):
    base = Path(rundir).resolve()
    rows = []
    for pin in pins or ():
        path = Path(pin["path"])
        rel = (path.resolve().relative_to(base) if path.is_absolute() else path).as_posix()
        rows.append({"path": rel, "sha256": pin["sha256"]})
    return rows


def _held_lease(claim=None):
    """The lease this process holds (``machine_lease.working()``), never the caller's object. A
    claim is at most an id: a different id is refused. Returns (lease, error)."""
    import os
    from . import machine_lease
    held = machine_lease.working()
    if held is None or held.pid != os.getpid():
        return None, GateError("lease_missing" if claim is None else "lease_not_held", "launch", PROVIDER,
                               "this process holds no machine lease" if claim is None else
                               f"lease {str(getattr(claim, 'lease_id', None))[:12]} is not the lease this process holds",
                               "Acquire the machine lease for this run and node, and dispatch under it.")
    if claim is not None and getattr(claim, "lease_id", None) != held.lease_id:
        return None, GateError("lease_not_held", "launch", PROVIDER,
                               f"lease {str(getattr(claim, 'lease_id', None))[:12]} is not the lease this process holds",
                               "Dispatch under the lease this process acquired.")
    return held, None


def dispatch_action(rundir, action, lease=None, *, write=True):
    """The action a delegated screen dispatch is decided on: the screen's pins plus a dispatch
    record binding the screen digest to the held lease, its run and its node. Its digest is what
    the R1 receipt must name, so a receipt for the bare screen or another lease does not match.
    ``lease`` is an id claim; the record binds ``machine_lease.working()``."""
    from .rdj_loop import action_digest
    held, error = _held_lease(lease)
    if error is not None:
        raise ValueError(error.message)
    record = {"kind": "delegated-dispatch", "action_digest": action.get("digest"),
              "lease_id": held.lease_id, "node_id": held.node_id,
              "rundir": str(Path(rundir).resolve())}
    raw = _canonical(record)
    rel = f"{ACTIONS_DIR}/dispatch/{_sha(raw)}.json"
    if write:
        path = Path(rundir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)
    pins = _rel_pins(rundir, action.get("pins")) + [{"path": rel, "sha256": _sha(raw)}]
    return {**action, "pins": pins, "digest": action_digest(pins), "scope": "screen", "floor": "R1",
            "lease": {"lease_id": record["lease_id"], "node_id": record["node_id"]}}


def _lease_errors(rundir, action, lease):
    held, error = _held_lease(lease)
    if error is not None:
        return [error]
    if held.rundir is None or Path(held.rundir).resolve() != Path(rundir).resolve() \
            or action.get("node_id") != held.node_id:
        return [GateError("lease_mismatch", "launch", PROVIDER,
                          "the held lease was taken for another run or node than this dispatch",
                          "Acquire the lease for this run and node.")]
    return []


def delegated_dispatch_errors(rundir, action, lease=None):
    """P15: refuse a delegated screen launch without an R1 RDJ receipt for exactly this action
    under exactly the lease this process holds."""
    errors = []
    if action.get("kind") not in SCREEN_KINDS or action.get("rung") not in (None, "dry", "smoke"):
        errors.append(GateError("not_a_screen_launch", "launch", PROVIDER,
                                f"{action.get('kind')} is not a screen; bulk and scan dispatch need their R2 route",
                                "Dispatch a dry, smoke or single-point screen, or take the R2 launch route."))
    lease_errors = _lease_errors(rundir, action, lease)
    if lease_errors:
        return errors + lease_errors
    bound = dispatch_action(rundir, action, lease, write=False)
    return errors + check_transition(rundir, "launch", bound)


SCREEN_PLANS = {"dry": "dry_run", "smoke": "smoke_launch"}


def _delegated_facts(rundir):
    """(facts, error): the run's facts through ``review_points._facts``, which refuses a contract
    that differs from its run_init snapshot; any failure is a refusal, never a pass."""
    from .review_points import _facts
    try:
        return _facts(Path(rundir)), None
    except (OSError, ValueError, KeyError, TypeError, custody.CustodyError) as exc:
        return None, str(exc)


def _is_delegated(facts):
    contract = facts.get("contract") or {}
    return bool(facts.get("delegated") or contract.get("autonomy"))


def screen_action(rundir, required_plan, command, context, *, write=False):
    """The screen action of one authorized launch: its plan rung, command and stage, on the held
    lease's node."""
    held, _ = _held_lease()
    value = {"required_plan": required_plan, "command": [str(c) for c in command],
             "stage": (context or {}).get("stage"), "context_kind": (context or {}).get("kind")}
    return value_action(rundir, SCREEN_PLANS[required_plan], {"screen": value},
                        f"Launch the {required_plan} screen {value['stage'] or ''}".strip(), write=write,
                        node_id=None if held is None else held.node_id)


BULK_PLANS = {"full": "bulk_launch", "scan": "scan_launch"}


def bulk_action(rundir, required_plan, command, context, *, write=False):
    """The R2 action of one full or scan launch: its rung, command and stage, on the plan node
    the held lease (or the launch context) names. The executor provider needs that node's
    worker receipt or host waiver."""
    held, _ = _held_lease()
    node_id = held.node_id if held is not None and held.node_id else (context or {}).get("node_id")
    value = {"required_plan": required_plan, "command": [str(c) for c in command],
             "stage": (context or {}).get("stage"), "context_kind": (context or {}).get("kind"), "node_id": node_id}
    action = value_action(rundir, BULK_PLANS[required_plan], {"launch": value},
                          f"Launch the {required_plan} rung {value['stage'] or ''}".strip(), write=write,
                          node_id=node_id, floor="R2")
    return {**action, "rung": required_plan}


def launch_errors(rundir, required_plan, command, context):
    """The launch authorization's call. Steering is checked for every launch first. On a
    delegated epoch-two run a dry or smoke launch then needs ``delegated_dispatch_errors`` (P15)
    to pass, and a full or scan launch needs the R2 launch gate (``require_delegated``).
    Pre-release and undelegated runs keep their existing authorization. Messages are strings."""
    permitted, reason = dispatch_permitted(rundir, (context or {}).get('node_id'))
    if not permitted:
        return [f'gate_wiring:steering_refused: {reason}']
    if required_plan in BULK_PLANS:
        return [f"{e.provider}:{e.code}: {e.message}"
                for e in delegated_errors(rundir, "launch", bulk_action(rundir, required_plan, command, context))]
    if required_plan not in SCREEN_PLANS:
        return []
    try:
        recorded = bool(_events(rundir, "run_init"))
    except (custody.CustodyError, OSError, ValueError) as exc:
        return [f"gate_wiring:gate_inputs_invalid: custody is unreadable: {exc}"]
    if not (recorded or epoch_two(rundir)):
        return []  # A pre-release run keeps its launch authorization.
    facts, error = _delegated_facts(rundir)
    if error is not None:
        return [f"gate_wiring:gate_inputs_invalid: {error}"]
    missing = _run_init_errors(rundir, "launch")
    if missing:
        return [f"{e.provider}:{e.code}: {e.message}" for e in missing]
    if not _is_delegated(facts):
        return []
    action = screen_action(rundir, required_plan, command, context)
    return [f"{e.provider}:{e.code}: {e.message}" for e in delegated_dispatch_errors(rundir, action)]


# ---------------------------------------------------------------- R2/R3 on delegated runs

def delegated_errors(rundir, gate, action):
    """R2/R3 wiring: ``check_transition`` for ``gate`` on a delegated epoch-two run.

    A pre-release run and an undelegated epoch-two run return [] and keep their decision: there
    the operator's own command is the human decision. An epoch-two run without ``run_init``, or
    one whose facts cannot be read (a contract changed after ``run_init``), is refused."""
    try:
        recorded = bool(_events(rundir, "run_init"))
    except (custody.CustodyError, OSError, ValueError) as exc:
        return [GateError("gate_inputs_invalid", gate, PROVIDER, f"custody is unreadable: {exc}",
                          "Restore the run's custody ledgers.", ("custody:inputs",))]
    if not (recorded or epoch_two(rundir)):
        return []
    facts, error = _delegated_facts(rundir)
    if error is not None:
        return [GateError("gate_inputs_invalid", gate, PROVIDER, error, "Restore the pinned contract and plan.",
                          ("inputs:contract-plan",))]
    missing = _run_init_errors(rundir, gate)
    if missing:
        return missing
    if not _is_delegated(facts):
        return []
    return check_transition(rundir, gate, action)


def require_delegated(rundir, gate, action):
    """Raise ``GateRefused`` unless ``delegated_errors`` is empty. The R2/R3 call sites use it."""
    errors = delegated_errors(rundir, gate, action)
    if errors:
        raise GateRefused(gate, errors)


def _rel_digests(rundir, paths):
    base = Path(rundir).resolve()
    rows = {}
    for path in paths:
        path = Path(path)
        full = path if path.is_absolute() else base / path
        rel = full.resolve().relative_to(base).as_posix() if full.resolve().is_relative_to(base) else str(full)
        rows[rel] = _sha(full.read_bytes()) if full.is_file() and not full.is_symlink() else None
    return rows


def plan_action(rundir, required_plan, *, write=False):
    """The R2 ``approve_plan`` action of a delegated CHECK-IN 1 approval: the plan rung, the
    contract bytes and the request-plan pin it approves."""
    contract = Path(rundir) / custody.TASK_CONTRACT
    value = {"required_plan": required_plan, "task_contract_sha256": _sha(contract.read_bytes()),
             "request_plan": (_contract(rundir) or {}).get("request_plan")}
    return value_action(rundir, "plan_approval", {"approve_plan": value},
                        f"Approve the {required_plan} plan under the delegation", write=write, floor="R2")


def checkin2_action(rundir, *, write=False):
    """The R2 ``checkin2_accept`` action of a delegated CHECK-IN 2 GO: every file the GO binds."""
    from .workflow_state import checkin2_go_input_paths
    try:
        paths = checkin2_go_input_paths(str(rundir))
    except (OSError, ValueError, KeyError, TypeError):
        # An unreadable manifest binds only the fixed records; the GO's own check refuses it.
        paths = [Path(rundir) / "inputs/checkin2.json", Path(rundir) / "inputs/checkin1_approval.json"]
    files = _rel_digests(rundir, paths)
    return value_action(rundir, "checkin2_go", {"checkin2_accept": files},
                        "Accept CHECK-IN 2 under the delegation", write=write, floor="R2")


def delivered_claims(rundir):
    """Digest of each delivered claim (``outputs/claims/*.json``) without the enforcement record
    that packaging stamps into it."""
    base = Path(rundir)
    claims = {}
    for path in sorted((base / "outputs/claims").glob("*.json")):
        raw = path.read_bytes()
        try:
            value = json.loads(raw)
        except ValueError:
            value = None
        rel = path.relative_to(base).as_posix()
        claims[rel] = _sha(_canonical({k: v for k, v in value.items() if k != "enforcement"})) \
            if isinstance(value, dict) else _sha(raw)
    return claims


def delivery_action(rundir, *, write=False):
    """The R3 ``delivery`` action of result packaging: the delivered claims."""
    return value_action(rundir, "delivery", {"delivery": {"claims": delivered_claims(rundir)}},
                        "Package the run's delivered claims", write=write, floor="R3")


def export_action(rundir, request_path, *, write=False):
    """The R3 ``export`` action of a submission export: the request bytes and the delivered claims."""
    value = {"request_sha256": _sha(Path(request_path).read_bytes()), "claims": delivered_claims(rundir)}
    return value_action(rundir, "export", {"export": value}, "Export the run's submission package",
                        write=write, floor="R3")


def spend_action(rundir, invocations, *, write=False):
    """The R3 ``spend_above_ceiling`` action: the invocations requested above the original
    ceiling and the ceilings record they spend under."""
    from .run_ceilings import RECORD
    if type(invocations) is not int or invocations < 1:
        raise ValueError("a spend names a positive number of invocations")
    record = Path(rundir) / RECORD
    value = {"invocations": invocations,
             "ceilings_sha256": _sha(record.read_bytes()) if record.is_file() else None}
    action = value_action(rundir, "spend", {"spend_above_ceiling": value},
                          f"Spend {invocations} invocation(s) above the original ceiling", write=write, floor="R3")
    return {**action, "invocations": invocations}


# ---------------------------------------------------------------- PHYS-RDJ

def _value_record(value):
    if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"]:
        raise ValueError("a physics value names itself")
    if value.get("origin") not in VALUE_ORIGINS or type(value.get("critical")) is not bool or "value" not in value:
        raise ValueError(f"a physics value carries value, origin in {VALUE_ORIGINS} and critical")
    return {k: value[k] for k in ("name", "value", "origin", "critical", "node_id") if k in value}


def physics_value_action(rundir, value, *, write=True):
    record = _value_record(value)
    return value_action(rundir, "physics_value", {"physics_value": record},
                        f"Adopt agent-inferred physics value {record['name']}", write=write,
                        node_id=record.get("node_id"))


def physics_value_errors(rundir, value, *, gate="approve_plan", delegated=None):
    """PHYS-RDJ: a delegated run may adopt an agent-inferred physics-critical value only with an
    authorizing RDJ receipt for exactly that value whose case holds an externally verified anchor.

    Epoch and delegation come from ``review_points._facts`` (bound to run_init), never from the
    contract flags alone; ``delegated=True`` is the delegated approval path's own assertion. A run
    whose facts cannot be read is refused. A pre-release contract keeps its own path ([])."""
    record = _value_record(value)
    if not (record["critical"] and record["origin"] == "agent_inferred"):
        return []
    facts, error = _delegated_facts(rundir)
    if error is not None:
        return [GateError("gate_inputs_invalid", gate, PROVIDER, error, "Restore the pinned contract and plan.",
                          ("inputs:contract-plan",))]
    if facts.get("agent_layer_epoch") != EPOCH:
        return []
    missing = _run_init_errors(rundir, gate)
    if missing:
        return missing
    if not (delegated or _is_delegated(facts)):
        return []
    from . import rdj_loop
    action = physics_value_action(rundir, value, write=False)
    errors = list(rdj_loop.gate_errors(Path(rundir), gate, action))
    if errors:
        return errors
    accepted = rdj_loop.authorizing_receipt(Path(rundir), gate, action)
    anchors = [a for a in ((accepted or {}).get("case") or {}).get("anchors", []) if a.get("verified") == "external"]
    if not anchors:
        return [GateError("physics_value_unanchored", gate, PROVIDER,
                          f"the receipt for {record['name']} rests on no externally verified anchor",
                          "Anchor the value to a tool output, measurement, input or user requirement.",
                          (f"{ACTIONS_DIR}/physics_value/{action['digest']}.json",))]
    return _tripwire(rundir, gate, action, [])


# ---------------------------------------------------------------- T13 cost reporting

def _usage(rundir):
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unreported_calls": 0, "receipts": 0}
    base = Path(rundir).resolve()
    seen = set()
    for row in custody.rows(rundir, "workers"):
        rel, digest = row["record"]["path"], row["record"]["sha256"]
        if (rel, digest) in seen:
            continue
        seen.add((rel, digest))
        path = base / rel
        try:
            if path.is_symlink() or _sha(path.read_bytes()) != digest:
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(receipt, dict) or not receipt.get("rdj"):
            continue
        totals["receipts"] += 1
        usage = receipt.get("usage") or {}
        if not usage.get("reported"):
            totals["unreported_calls"] += 1
        for key in ("input_tokens", "output_tokens"):
            if type(usage.get(key)) is int:
                totals[key] += usage[key]
        if isinstance(usage.get("cost_usd"), (int, float)) and not isinstance(usage["cost_usd"], bool):
            totals["cost_usd"] += usage["cost_usd"]
    return totals


def cost_report(rundir):
    """T13: RDJ model calls (the custody role ledger), tokens and cost from the registered worker
    receipts that still verify, per-case outcomes and budget state. Read-only."""
    from . import rdj_loop
    from .rdj_anchor import policy
    budgets = policy()["budgets"]
    calls = custody.rows(rundir, "roles")
    outcomes = {}
    for row in custody.rows(rundir, "receipts"):
        outcomes[row["record"]["case_id"]] = row["record"]["outcome"]
    cases = {}
    for row in custody.rows(rundir, "cases"):
        case_id = row["record"]["case_id"]
        status = rdj_loop.status(rundir, case_id)
        cases[case_id] = {"gate": row["record"]["gate"], "calls": sum(1 for c in calls if c["record"]["case_id"] == case_id),
                          "phase": status.get("phase"),
                          "budget_exhausted": status.get("phase") == "budget_exhausted"
                          or (status.get("budget") or {}).get("reason") is not None,
                          "outcome": outcomes.get(case_id)}
    usage = _usage(rundir)
    run_cap = budgets["max_model_calls_per_run"]
    return {"schema_version": 1, "kind": "rdj-cost-report", "rundir": str(Path(rundir).resolve()),
            "rdj": {"calls": len(calls), **usage, "cases": cases,
                    "budget": {"max_model_calls_per_run": run_cap, "remaining": max(0, run_cap - len(calls)),
                               "max_model_calls_per_action": budgets["max_model_calls_per_action"]},
                    "exhausted": len(calls) >= run_cap or any(c["budget_exhausted"] for c in cases.values())},
            "tokens_are_reported_by": "registered worker receipts (unreported calls are counted, not estimated)"}


# ---------------------------------------------------------------- CLI: ravel respond | steer | gate-wiring

def _print(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def _body(args):
    return args.text if args.text is not None else args.text_file.read_text(encoding='utf-8') if args.text_file else None


def _policy_flags(args):
    value = {'autonomy': args.autonomy, 'checkin_thresholds': {}, 'hard_ceilings': {},
             'signoff_steps': args.signoff_step, 'unknown_cost': args.unknown_cost,
             'on_pause': args.on_pause, 'result_acceptance': args.result_acceptance}
    for target, items in (('checkin_thresholds', args.checkin_threshold), ('hard_ceilings', args.hard_ceiling)):
        for item in items:
            key, raw = item.split('=', 1)
            value[target][key] = None if raw == 'null' else float(raw)
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel gate-wiring', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    resp = sub.add_parser('respond', help='record explicit decisions or result disposition')
    resp.add_argument('action', nargs='?', choices=('accept', 'reject', 'rework'))
    resp.add_argument('--approve', action='append', default=[], metavar='CASE_ID')
    resp.add_argument('--reopen', action='append', default=[], metavar='ACTION_DIGEST')
    resp.add_argument('--withdraw', action='append', default=[], metavar='CASE_ID:FINDING_ID')
    steer = sub.add_parser('steer', help='record typed live steering and acknowledgement')
    steer.add_argument('action', nargs='?', choices=('note', 'require', 'redirect', 'pause', 'resume', 'veto', 'priority', 'policy', 'ack', 'state', 'init'))
    steer.add_argument('event_id', nargs='?')
    steer.add_argument('--effect', choices=STEERING_EFFECTS)
    steer.add_argument('--affects', default='', help='comma-separated plan node ids; empty means the whole study')
    steer.add_argument('--span', help='START:END of the cited text')
    steer.add_argument('--interpretation')
    steer.add_argument('--amended-plan', type=Path)
    scope = steer.add_mutually_exclusive_group()
    scope.add_argument('--within-scope', action='store_true', help='redirect reconciles existing approved scope')
    scope.add_argument('--scope-increase', action='store_true',
                       help='the instruction enlarges the approved scope; plan reapproval is required')
    steer.add_argument('--supersedes', help='veto event id released by resume')
    steer.add_argument('--priority', type=int, default=0, help='larger numbers dispatch first among eligible pending nodes')
    steer.add_argument('--set', nargs='?', const='flags', metavar='FILE|flags')
    steer.add_argument('--autonomy', choices=('manual', 'bounded_delegated'), default='manual')
    steer.add_argument('--unknown-cost', choices=('ask', 'pilot_first'), default='ask')
    steer.add_argument('--on-pause', choices=('drain', 'cancel'), default='drain')
    steer.add_argument('--result-acceptance', choices=('physicist', 'review_only'), default='physicist')
    steer.add_argument('--checkin-threshold', action='append', default=[], metavar='RESOURCE=NUMBER|null')
    steer.add_argument('--hard-ceiling', action='append', default=[], metavar='RESOURCE=NUMBER|null')
    steer.add_argument('--signoff-step', action='append', default=[])
    for parser in (resp, steer):
        parser.add_argument('--rundir', type=Path, required=True)
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--text')
        group.add_argument('--text-file', type=Path)
        parser.add_argument('--authority', choices=('unknown', 'delegated_machine', 'scripted_experiment'), default='unknown')
        parser.add_argument('--expected-epoch', type=int)
    ci1 = sub.add_parser('checkin1', help='record CHECK-IN 1 response and display the current steering policy')
    ci1.add_argument('--rundir', type=Path, required=True)
    ci1.add_argument('--quote')
    cost = sub.add_parser('cost', help='RDJ calls, tokens and budget state')
    cost.add_argument('--rundir', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'respond':
            body = _body(args)
            if args.action:
                if args.approve or args.reopen or args.withdraw:
                    raise ValueError('result disposition is separate from decision approval')
                _print(record_result_disposition(args.rundir, args.action, body or args.action,
                                                 authority=args.authority, expected_epoch=args.expected_epoch))
            else:
                withdraw = [tuple(w.split(':', 1)) for w in args.withdraw]
                if any(len(w) != 2 for w in withdraw):
                    raise ValueError('--withdraw takes CASE_ID:FINDING_ID')
                _print(respond(args.rundir, body, approve=args.approve, reopen=args.reopen, withdraw=withdraw))
        elif args.command == 'checkin1':
            result = record_checkin1(args.rundir, quote=args.quote)
            _print({'checkin1': result, 'steering_policy': steering_policy(args.rundir),
                    'steering_policy_text': render_steering_policy(args.rundir)})
        elif args.command == 'steer':
            if args.action == 'state':
                _print(steering_state(args.rundir))
            elif args.action == 'init':
                if not args.rundir.is_dir():
                    raise ValueError('steer init names an existing run directory')
                initialize_steering(args.rundir, route='operator')
                _print({'initialized': True, **steering_state(args.rundir)})
            elif args.action == 'ack':
                _print(ack_steering(args.rundir, args.event_id, interpretation=args.interpretation,
                                    amended_plan=args.amended_plan, expected_epoch=args.expected_epoch))
            elif args.action == 'policy':
                if args.set is None:
                    raise ValueError('policy requires --set FILE or --set flags')
                if args.set == 'flags':
                    value = _policy_flags(args)
                    body = _body(args) or shlex.join(list(sys.argv[1:] if argv is None else argv))
                else:
                    body = Path(args.set).read_text(encoding='utf-8')
                    value = json.loads(body)
                _print(set_steering_policy(args.rundir, value, source_text=body,
                                           authority=args.authority, expected_epoch=args.expected_epoch))
            else:
                effect = {'require': 'requirement'}.get(args.action, args.action) or args.effect
                if effect is None:
                    raise ValueError('steer requires a typed action or --effect')
                if args.effect is not None and args.action is not None:
                    raise ValueError('choose typed action or --effect')
                span = tuple(int(x) for x in args.span.split(':', 1)) if args.span else None
                _print(record_steering(args.rundir, _body(args) or args.action, effect=effect,
                                       affected_nodes=[n for n in args.affects.split(',') if n], span=span,
                                       authority=args.authority,
                                       scope_increase=False if args.within_scope else True if args.scope_increase else None,
                                       supersedes=args.supersedes, priority=args.priority, expected_epoch=args.expected_epoch))
        else:
            _print(cost_report(args.rundir))
    except (OSError, ValueError) as exc:
        print(f'ravel gate-wiring: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
