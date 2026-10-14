"""RAVEL custody records for decision justification, kept outside the run directory.

The proposer is an agent with a shell in the run directory, so nothing written there
can grant authority by itself. The records that do grant authority live under
``machine_state_root()/rdj/<run key>/`` as append-only, hash-chained JSON lines:

- ``inputs``: the input snapshot taken at run initialization and at CHECK-IN 1;
- ``user_text``: the original prompt, the CHECK-IN 1 response and user steering,
  each recorded by RAVEL's user-message path;
- ``approvals``: the user decisions ledger: ``approve`` one case, ``reopen`` one action or
  ``withdraw`` one finding of a case, written by the CHECK-IN response and steering paths;
- ``acquisitions``: input files the operator path fetched or the user uploaded, by path and
  sha256, written by that path (never by an agent session);
- ``checks``: check results written by a recognized check (a registered validator or a
  shipped invariant), registered by the check runner;
- ``workers``, ``hosts``, ``graphs``, ``stages``: worker receipts registered by the
  worker dispatcher, agent hosts registered by the operator path, model receipts
  registered by the RDJ dispatcher and stage receipts registered by the stage supervisor;
- ``cases``, ``roles``, ``receipts``: cases opened, role calls reserved and RDJ
  receipts written, used for budgets, escalation and the gate;
- ``checkin1_approvals``: the digest of every CHECK-IN 1 approval record RAVEL wrote, human
  or delegated, so deleting or rewriting the run's approval file cannot reset the baseline a
  delegated re-approval classifies changes against;
- ``journal-<case_id>``: the mirror of each case journal, with the saved case and
  state contents under ``blobs/`` so an interrupted save can be restored.

A run is keyed by the ``run_id`` of its task contract once RAVEL binds it at run
initialization (``bind_run``); a moved run is served again only after an explicit
``relocate``. A run without a ``run_id`` is keyed by its resolved path.

Every directory RAVEL creates also gets an identity record (``run-identity.json``,
``bind_new_run``): a ``run_id`` that travels with a renamed or copied directory and is
bound to the location where the run is served. That binding does not change the key:
custody of such a run stays keyed by its location, so a copy or a renamed directory has
no custody of its own, and the binding is how RAVEL recognizes it as an existing run
instead of a new one (``location``).

A process running as the same OS user can still write this directory. Keeping it
outside the run directory stops an agent that edits run files; separating the agent
at the OS level is the worker sandbox's job.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .state_io import file_lock

LEDGERS = re.compile(r"(inputs|user_text|approvals|acquisitions|checks|workers|hosts|graphs|stages|cases|roles|receipts"
                     r"|review_acceptances|checkin1_approvals|steering|journal-[A-Za-z0-9_.-]{1,120})")
INPUT_EVENTS = ("run_init", "checkin1")
USER_SOURCES = ("prompt", "checkin1_response", "user_steering")
APPROVAL_SOURCES = ("checkin1_response", "user_steering")
DECISIONS = ("approve", "reopen", "withdraw")
ACQUISITION_SOURCES = ("user_upload", "acquisition")
WORKER_LABELS = ("transport_attested", "host_attested", "self_attested")
CHECK_RESULT_KIND = "ravel-check-result"
CHECK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")
INDEX = "runs.jsonl"
IDENTITIES = "identities.jsonl"  # bindings of identity records; these runs stay keyed by location
RUN_IDENTITY = "run-identity.json"
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}")
TASK_CONTRACT = "inputs/task_contract.json"
CI1_RESPONSE = "inputs/checkin1-response.txt"  # scientific_autonomy.CI1_RESPONSE
STEERING_DIR = "inputs/user-steering"


class CustodyError(ValueError):
    """A custody ledger is absent where required, or its chain does not verify."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _state():
    from . import machine_lease
    # Seam: the AGENT-INTERFACES s24 name when machine_lease defines it, else the same fixed per-uid directory.
    state_root = getattr(machine_lease, "machine_state_root", None) or machine_lease.ensure_machine_dir
    return Path(state_root()) / "rdj"


def _contract_run_id(base):
    try:
        contract = json.loads((base / TASK_CONTRACT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = contract.get("run_id") if isinstance(contract, dict) else None
    return value if isinstance(value, str) and RUN_ID.fullmatch(value) else None


def _record_run_id(base):
    """The ``run_id`` of the identity record RAVEL wrote into this directory, or None without one.

    A record that is present but cannot be read is refused: custody cannot tell which run the
    directory is, and it is never taken for a directory without an identity."""
    path = base / RUN_IDENTITY
    if not (path.is_symlink() or path.exists()):
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and not path.is_symlink() else None
    except (OSError, ValueError):
        value = None
    run_id = value.get("run_id") if isinstance(value, dict) and value.get("kind") == "run-identity" else None
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise CustodyError(f"the run identity record {path} cannot be read; custody cannot tell which run this "
                           "directory is")
    return run_id


def run_identity(rundir):
    """The identity a directory names: the ``run_id`` of its task contract, else of its identity record."""
    base = Path(rundir).resolve()
    return _contract_run_id(base) or _record_run_id(base)


def _bindings():
    return _read(_state() / INDEX)


def root(rundir):
    """The custody directory of one run: keyed by its bound ``run_id``, else by its resolved path."""
    base = Path(rundir).resolve()
    state = _state()
    if state.resolve().is_relative_to(base):
        raise CustodyError(f"the custody store {state} lies inside the run; the machine state root must be outside it")
    run_id = _contract_run_id(base)
    bindings = [r["record"] for r in _bindings()]
    here = [b for b in bindings if b["path"] == str(base)]
    if run_id is None:
        if here:
            raise CustodyError(f"the run at {base} was bound to {here[-1]['run_id']!r}; its task contract no longer "
                               "names a run_id")
        return state / hashlib.sha256(str(base).encode()).hexdigest()[:32]
    mine = [b for b in bindings if b["run_id"] == run_id]
    if not mine:
        raise CustodyError(f"run_id {run_id!r} is not bound in custody; RAVEL binds it at run initialization")
    if mine[-1]["path"] != str(base):
        raise CustodyError(f"run {run_id!r} was relocated from {mine[-1]['path']}; serve it here only after "
                           "rdj_custody.relocate")
    if here and here[-1]["run_id"] != run_id:
        raise CustodyError(f"the run at {base} is bound to {here[-1]['run_id']!r}, not {run_id!r}")
    return state / ("run-" + hashlib.sha256(run_id.encode()).hexdigest()[:32])


def _bind(rundir, run_id, *, move):
    base = Path(rundir).resolve()
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("run_id is a short identifier")
    index = INDEX
    if _contract_run_id(base) != run_id:
        if _record_run_id(base) != run_id:
            raise ValueError(f"the task contract of {base} does not name run_id {run_id!r}")
        if move:
            # Its custody is keyed by location: an index row alone would serve nothing at the new path.
            raise ValueError(f"run {run_id!r} is identified by its identity record and is served only at its "
                             "recorded location")
        index = IDENTITIES

    def check(rows):
        mine = [r["record"] for r in rows if r["record"]["run_id"] == run_id]
        if move and not mine:
            return f"run {run_id!r} was never bound; bind it at run initialization"
        if not move and mine:
            return f"run {run_id!r} is already bound (to {mine[-1]['path']}); a moved run is relocated"
        return None
    return _append(_state() / index, {"run_id": run_id, "path": str(base), "event": "relocate" if move else "bind"},
                   check)


def bind_run(rundir, run_id):
    """Bind a new run's ``run_id`` to its path. Called by RAVEL at run initialization only.

    The ``run_id`` is the one the task contract names, or the one in the directory's identity
    record; custody of a run identified by its record stays keyed by its location."""
    return _bind(rundir, run_id, move=False)


def bind_new_run(rundir):
    """Give a directory its identity: write the identity record and bind it to this location.

    Called where RAVEL starts the custody of a directory (``gate_wiring.initialize_steering``,
    a child binding). The record grants nothing; it lets custody recognize the directory after
    a rename or a copy. Returns the new ``run_id``."""
    import uuid
    base = Path(rundir).resolve()
    run_id = uuid.uuid4().hex
    with (base / RUN_IDENTITY).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"schema_version": 1, "kind": "run-identity", "run_id": run_id,
                                 "grants_authority": False}, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        bind_run(base, run_id)
    except BaseException:
        (base / RUN_IDENTITY).unlink(missing_ok=True)  # an unbound record would name a run custody never knew
        raise
    return run_id


def location(run_id):
    """The path a bound ``run_id`` is recorded at (its latest binding), or None when it was never bound."""
    state = _state()
    paths = [r["record"]["path"] for name in (IDENTITIES, INDEX) for r in _read(state / name)
             if r["record"]["run_id"] == run_id]
    return paths[-1] if paths else None


def relocate(rundir, run_id):
    """Serve a moved run's custody at its new path (an explicit operator action)."""
    return _bind(rundir, run_id, move=True)


def stores():
    """``(name, directory)`` of every run custody on this machine, for reconciling a run location."""
    state = _state()
    if not state.is_dir():
        return []
    return sorted((path.name, path) for path in state.iterdir() if path.is_dir() and not path.is_symlink())


def store_rows(directory, ledger):
    """Every verified line of one ledger of a custody directory ``stores`` listed."""
    if not isinstance(ledger, str) or not LEDGERS.fullmatch(ledger):
        raise CustodyError(f"unknown custody ledger {ledger!r}")
    try:
        return _read(Path(directory) / (ledger + ".jsonl"))
    except CustodyError as exc:
        raise CustodyError(f"{exc} (custody {Path(directory).name})") from None


def _path(rundir, ledger):
    if not isinstance(ledger, str) or not LEDGERS.fullmatch(ledger):
        raise CustodyError(f"unknown custody ledger {ledger!r}")
    return root(rundir) / (ledger + ".jsonl")


def _read(path):
    rows, previous = [], None
    if not path.exists():
        return rows
    for seq, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(line)
            body = {k: v for k, v in row.items() if k != "digest"}
            valid = row.get("seq") == seq and row.get("prev") == previous and _digest(body) == row.get("digest")
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise CustodyError(f"custody ledger {path.name} does not verify at line {seq}")
        previous = row["digest"]
        rows.append(row)
    return rows


def rows(rundir, ledger):
    """Every verified line of a ledger, oldest first."""
    return _read(_path(rundir, ledger))


def _append(path, record, check=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_suffix(".lock")):
        existing = _read(path)
        if check is not None:
            refusal = check(existing)
            if refusal:
                raise CustodyError(refusal)
        last = existing[-1] if existing else None
        ns = max(time.time_ns(), (last["ns"] + 1) if last else 0)
        line = {"seq": len(existing), "prev": last["digest"] if last else None, "ns": ns,
                "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "record": record}
        line["digest"] = _digest(line)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return line


def append(rundir, ledger, record, *, check=None):
    """Append one hash-chained line; returns it (with ``ns``, a monotonic ordering stamp).

    ``check(existing_rows)`` runs under the ledger lock; a returned reason refuses the
    append, so a count or uniqueness rule and its reservation are one atomic step."""
    return _append(_path(rundir, ledger), record, check)


@contextmanager
def run_lock(rundir):
    """One lock per run for decisions that read several ledgers before writing (opening a case)."""
    directory = root(rundir)
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory / "run.lock"):
        yield


def put_blob(rundir, value):
    """Store a JSON value under custody ``blobs/`` by digest; returns the digest."""
    digest = _digest(value)
    path = root(rundir) / "blobs" / (digest + ".json")
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp-" + str(os.getpid()))
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")  # keeps key order
        os.replace(temporary, path)
    return digest


def get_blob(rundir, digest):
    path = root(rundir) / "blobs" / (str(digest) + ".json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CustodyError(f"custody holds no saved content {str(digest)[:12]}") from None
    if _digest(value) != digest:
        raise CustodyError(f"custody content {str(digest)[:12]} does not verify")
    return value


# ---------------------------------------------------------------- input snapshots

def _ravel_written(rel, patterns):
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in patterns)


def record_input_snapshot(rundir, event, *, limit=None):
    """Record the digests of every regular file under ``inputs/`` at a RAVEL-owned event.

    Called at run initialization, before any agent session acts on the run, and at
    CHECK-IN 1, after the planning session has had a shell. Each event is recorded once.
    Files RAVEL itself writes (policy ``ravel_written_inputs``) are listed but never count
    as external input. At CHECK-IN 1 a file that is new or changed since the run_init
    snapshot counts as external only when RAVEL can vouch for its exact bytes: it is user
    text RAVEL recorded, or a registered acquisition or user upload names its path and
    sha256. Otherwise it is ``unvouched``. The agent write log is proposer-writable: its
    silence never vouches, and a file it lists is ``unvouched`` whatever else names it.
    A run whose inputs exceed the policy file limit fails here, loudly, at the event.
    """
    from .rdj_anchor import generated_paths, policy
    if event not in INPUT_EVENTS:
        raise ValueError(f"input snapshots are taken at {INPUT_EVENTS}")
    pol = policy()
    limit = pol["input_snapshot_max_files"] if limit is None else limit
    base = Path(rundir).resolve()
    files = {}
    if (base / "inputs").is_dir():
        for path in sorted((base / "inputs").rglob("*")):
            if path.is_file() and not path.is_symlink():
                if len(files) >= limit:
                    raise CustodyError(f"the {event} input snapshot exceeds its file limit ({limit}, policy "
                                       "input_snapshot_max_files); no input of this run can be external")
                files[path.relative_to(base).as_posix()] = _sha_file(path)
    unvouched = []
    if event == "checkin1":
        # The latest run_init row: a RAVEL-owned rewrite before CHECK-IN 1 supersedes the first.
        first = next((r["record"] for r in reversed(rows(rundir, "inputs")) if r["record"]["event"] == "run_init"), None)
        vouched = {(r["record"]["path"], r["record"]["sha256"]) for r in rows(rundir, "user_text")} \
            | {(r["record"]["path"], r["record"]["sha256"]) for r in rows(rundir, "acquisitions")}
        written = generated_paths(base)
        for rel, digest in files.items():
            if (first or {"files": {}})["files"].get(rel) == digest:
                continue
            if (rel, digest) not in vouched or rel in written:
                unvouched.append(rel)
    record = {"event": event, "files": files,
              "ravel_written": sorted(r for r in files if _ravel_written(r, pol["ravel_written_inputs"])),
              "unvouched": unvouched}

    def once(existing):
        if any(r["record"]["event"] == event for r in existing):
            return f"the {event} input snapshot is already recorded"
        return None
    try:
        return append(rundir, "inputs", record, check=once)
    except CustodyError as exc:
        raise ValueError(str(exc)) from None


def register_acquisition(rundir, rel, *, source):
    """Record an input file the operator path fetched (``acquisition``) or the user uploaded
    (``user_upload``), by path and the sha256 of its bytes now. Called by those paths only;
    the CHECK-IN 1 snapshot vouches for exactly these bytes."""
    if source not in ACQUISITION_SOURCES:
        raise ValueError(f"an acquisition source is one of {ACQUISITION_SOURCES}")
    base = Path(rundir).resolve()
    if not isinstance(rel, str) or ".." in Path(rel).parts or Path(rel).is_absolute() or not rel.startswith("inputs/"):
        raise ValueError("an acquisition names a run-relative file under inputs/")
    path = base / rel
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"the acquired file is absent: {rel}")
    return append(rundir, "acquisitions", {"source": source, "path": rel, "sha256": _sha_file(path)})


def _snapshot_row(rundir, before_ns):
    chosen = None
    for row in rows(rundir, "inputs"):
        if before_ns is None or row["ns"] < before_ns:
            chosen = row
    return chosen


def input_snapshot(rundir, *, before_ns=None):
    """``{rel: sha256}`` of external inputs from the latest snapshot before ``before_ns``, or None."""
    chosen = _snapshot_row(rundir, before_ns)
    if chosen is None:
        return None
    excluded = set(chosen["record"]["ravel_written"]) | set(chosen["record"].get("unvouched", ()))
    return {rel: digest for rel, digest in chosen["record"]["files"].items() if rel not in excluded}


def snapshot_digest(rundir, rel, *, before_ns=None, event=None):
    """The recorded digest of any input (RAVEL-written included) in the latest snapshot
    (or the snapshot of ``event``) before ``before_ns``, or None."""
    chosen = None
    for row in rows(rundir, "inputs"):
        if (before_ns is None or row["ns"] < before_ns) and (event is None or row["record"]["event"] == event):
            chosen = row
    return None if chosen is None else chosen["record"]["files"].get(rel)


# ---------------------------------------------------------------- user text

def _user_bytes(rundir, source, rel):
    base = Path(rundir).resolve()
    if not isinstance(rel, str) or ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ValueError("user text path must be run-relative")
    if source == "prompt":
        if rel != TASK_CONTRACT:
            raise ValueError("the original prompt is read from " + TASK_CONTRACT)
        contract = json.loads((base / rel).read_text(encoding="utf-8"))
        prompt = contract.get("prompt") if isinstance(contract, dict) else None
        if not isinstance(prompt, str):
            raise ValueError("the task contract carries no original prompt")
        bound = (contract.get("task_requirements") or {}).get("prompt_sha256")
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        if bound is None:
            raise ValueError("the task contract binds no task_requirements.prompt_sha256 for its prompt")
        if bound != digest:
            raise ValueError("the prompt differs from task_requirements.prompt_sha256")
        return prompt, digest
    if source == "checkin1_response":
        if rel != CI1_RESPONSE:
            raise ValueError("the CHECK-IN 1 response lives at " + CI1_RESPONSE)
    elif source == "user_steering":
        if not (rel.startswith(STEERING_DIR + "/") and rel.endswith(".txt")):
            raise ValueError(f"user steering lives under {STEERING_DIR}/*.txt")
    else:
        raise ValueError(f"user text source must be one of {USER_SOURCES}")
    path = base / rel
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"user text file is absent: {rel}")
    raw = path.read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def record_user_text(rundir, source, rel):
    """Record user text exactly as RAVEL received it. Called by prompt intake, the
    CHECK-IN 1 response path and the user-steering path; never by a proposer."""
    _, digest = _user_bytes(rundir, source, rel)
    return append(rundir, "user_text", {"source": source, "path": rel, "sha256": digest})


def record_user_steering(rundir, text):
    """Write one user steering message under ``inputs/user-steering/`` and record it."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("user steering text is required")
    base = Path(rundir).resolve() / STEERING_DIR
    base.mkdir(parents=True, exist_ok=True)
    index = len(rows(rundir, "user_text")) + 1
    while True:  # Concurrent writers each take the next free name.
        path = base / f"{index:04d}.txt"
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(text)
            break
        except FileExistsError:
            index += 1
    rel = path.relative_to(Path(rundir).resolve()).as_posix()
    record_user_text(rundir, "user_steering", rel)
    return {"path": rel, "sha256": _sha_file(path)}


def user_text_row(rundir, source, rel, digest):
    """The ledger line recording exactly this user text, or None."""
    for row in rows(rundir, "user_text"):
        record = row["record"]
        if record["source"] == source and record["path"] == rel and record["sha256"] == digest:
            return row
    return None


def user_text(rundir, source, rel):
    """``(text, sha256, ledger line)`` for recorded user text whose bytes still match, or raises."""
    text, digest = _user_bytes(rundir, source, rel)
    row = user_text_row(rundir, source, rel, digest)
    if row is None:
        raise CustodyError(f"{rel} is not user text that RAVEL recorded")
    return text, digest, row


# ---------------------------------------------------------------- human approvals

def _commit_line(rundir, case_id):
    lines = rows(rundir, "journal-" + case_id)
    if not lines or lines[0]["record"]["event"] != "proposal_committed":
        raise CustodyError(f"case {case_id} has no committed proposal in custody")
    return lines[0]


def _span(rundir, source, path, start, end, text):
    whole, digest, row = user_text(rundir, source, path)
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(whole)) or whole[start:end] != text:
        raise ValueError("the decision span does not equal the recorded text")
    return digest, row


def record_human_approval(rundir, *, case_id, source, path, start, end, text):
    """Record a human approval of one case. Called by the CHECK-IN response path only.

    The approving text is recorded user text (CHECK-IN 1 response or user steering,
    never the original prompt), recorded after the case's proposal commit, and the
    quoted span names the case id or the first 12 characters of the action digest.
    The record carries ``decision: approve``; only such records count as approvals.
    """
    if source not in APPROVAL_SOURCES:
        raise ValueError("a human approval quotes a CHECK-IN response or user steering, never the prompt")
    commit = _commit_line(rundir, case_id)
    data = commit["record"]["data"]
    if case_id not in text and data["digest"][:12] not in text:
        raise ValueError("the approval span names neither the case id nor the action digest")
    digest, row = _span(rundir, source, path, start, end, text)
    if row["ns"] <= commit["ns"]:
        raise ValueError("the approving text was recorded before the case was committed")
    return append(rundir, "approvals", {"decision": "approve", "case_id": case_id, "action_digest": data["digest"],
                                        "source": source, "path": path, "sha256": digest, "start": start,
                                        "end": end, "text": text})


def record_reopen(rundir, *, action_digest, source, path, start, end, text):
    """Record a user decision to reopen one action (after escalation or a spent case budget).

    Called by the user-steering and CHECK-IN response paths. The quoted span is exactly
    the first 12 characters of the action digest, in recorded user text."""
    if source not in APPROVAL_SOURCES:
        raise ValueError("a reopen decision quotes a CHECK-IN response or user steering, never the prompt")
    if not isinstance(action_digest, str) or len(action_digest) != 64 or text != action_digest[:12]:
        raise ValueError("a reopen decision quotes the first 12 characters of the action digest")
    digest, _ = _span(rundir, source, path, start, end, text)
    return append(rundir, "approvals", {"decision": "reopen", "case_id": None, "action_digest": action_digest,
                                        "source": source, "path": path, "sha256": digest, "start": start,
                                        "end": end, "text": text})


def record_withdrawal(rundir, *, case_id, finding_id, source, path, start, end, text):
    """Record a user decision to withdraw one critic finding of one case.

    Called by the user-steering and CHECK-IN response paths. The quoted span is exactly the
    finding id, in user text recorded after the case's proposal commit."""
    if source not in APPROVAL_SOURCES:
        raise ValueError("a withdrawal quotes a CHECK-IN response or user steering, never the prompt")
    if not isinstance(finding_id, str) or not finding_id or text != finding_id:
        raise ValueError("a withdrawal span quotes exactly the finding id")
    commit = _commit_line(rundir, case_id)
    digest, row = _span(rundir, source, path, start, end, text)
    if row["ns"] <= commit["ns"]:
        raise ValueError("the withdrawing text was recorded before the case was committed")
    return append(rundir, "approvals", {"decision": "withdraw", "case_id": case_id, "finding_id": finding_id,
                                        "action_digest": commit["record"]["data"]["digest"], "source": source,
                                        "path": path, "sha256": digest, "start": start, "end": end, "text": text})


def _decisions(rundir, decision, action_digest):
    found = []
    for row in rows(rundir, "approvals"):
        record = row["record"]
        if record.get("decision") != decision or record["action_digest"] != action_digest:
            continue
        try:
            whole, digest, _ = user_text(rundir, record["source"], record["path"])
        except (OSError, ValueError):
            continue
        if digest == record["sha256"] and whole[record["start"]:record["end"]] == record["text"]:
            found.append(row)
    return found


def approvals(rundir, case_id, action_digest):
    """Approvals (``decision: approve``) of exactly this case and action whose user text still verifies."""
    return [r["record"] for r in _decisions(rundir, "approve", action_digest) if r["record"]["case_id"] == case_id]


def last_reopen_ns(rundir, action_digest):
    """The ordering stamp of the latest verified reopen decision for an action, or 0."""
    return max((r["ns"] for r in _decisions(rundir, "reopen", action_digest)), default=0)


def withdrawals(rundir, case_id, action_digest):
    """Finding ids of this case that a verified user decision withdrew."""
    return {r["record"]["finding_id"] for r in _decisions(rundir, "withdraw", action_digest)
            if r["record"]["case_id"] == case_id}


# ---------------------------------------------------------------- registered receipts

def register_worker_receipt(rundir, rel, *, verified_label=None):
    """Register a worker receipt written by the worker dispatcher.

    ``verified_label`` is the attestation label the dispatcher's transport re-verification
    established (``transport_receipt``); the receipt's own ``attestation`` field is never read
    as a label. Without it the worker is ``self_attested``."""
    path = Path(rundir).resolve() / rel
    if ".." in Path(rel).parts or path.is_symlink() or not path.is_file():
        raise ValueError(f"worker receipt is absent: {rel}")
    if verified_label is not None and verified_label not in WORKER_LABELS:
        raise ValueError(f"a worker's verified label is one of {WORKER_LABELS}")
    return append(rundir, "workers", {"path": rel, "sha256": _sha_file(path),
                                      **({"verified_label": verified_label} if verified_label else {})})


def worker_row(rundir, rel, digest):
    """The latest registration of exactly this worker receipt, or None."""
    found = None
    for row in rows(rundir, "workers"):
        if row["record"]["path"] == rel and row["record"]["sha256"] == digest:
            found = row["record"]
    return found


def worker_registered(rundir, rel, digest):
    return worker_row(rundir, rel, digest) is not None


def _check_value(path, rel):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"check result is absent: {rel}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or value.get("schema_version") != 1 or value.get("kind") != CHECK_RESULT_KIND \
            or not isinstance(value.get("check_id"), str) or not CHECK_ID.fullmatch(value["check_id"]):
        raise ValueError(f"{rel} is not a {CHECK_RESULT_KIND} record")
    return value


def register_check_result(rundir, rel):
    """Register a check result written by a recognized check. Called by the check runner only;
    ``check:<check_id>`` then names the latest registration of that id."""
    base = Path(rundir).resolve()
    if not isinstance(rel, str) or ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ValueError("a check result is a run-relative file")
    value = _check_value(base / rel, rel)
    return append(rundir, "checks", {"check_id": value["check_id"], "path": rel, "sha256": _sha_file(base / rel)})


def check_result(rundir, check_id):
    """The registered check result named ``check_id`` whose file still has its registered bytes, or raises."""
    found = None
    for row in rows(rundir, "checks"):
        if row["record"]["check_id"] == check_id:
            found = row["record"]
    if found is None:
        raise ValueError(f"no registered check result {check_id}")
    path = Path(rundir).resolve() / found["path"]
    if path.is_symlink() or not path.is_file() or _sha_file(path) != found["sha256"]:
        raise ValueError(f"check result {check_id} differs from its registration")
    value = _check_value(path, found["path"])
    if value["check_id"] != check_id:
        raise ValueError(f"check result {check_id} names another check")
    return value


def register_host(rundir, identity):
    """Register an agent host for transport attestation. Called by the operator path
    (``ravel rdj run-roles --host-config``) with the identity ``AgentHost.from_config`` built."""
    if not isinstance(identity, dict) or not identity:
        raise ValueError("a registered host has a nonempty identity")
    return append(rundir, "hosts", {"host_sha256": _digest(identity), "identity": identity})


def host_registered(rundir, host_sha256):
    return any(r["record"]["host_sha256"] == host_sha256 for r in rows(rundir, "hosts"))


def register_graph_receipt(rundir, root_rel, receipt_sha256, host_sha256):
    """Register a model receipt that the RDJ dispatcher obtained from ``agent_graph``."""
    return append(rundir, "graphs", {"root": root_rel, "receipt_sha256": receipt_sha256, "host_sha256": host_sha256})


def graph_receipt_registered(rundir, root_rel, receipt_sha256, host_sha256):
    return any(r["record"] == {"root": root_rel, "receipt_sha256": receipt_sha256, "host_sha256": host_sha256}
               for r in rows(rundir, "graphs"))


def _stage_record(rundir, stage, attempt_id):
    from .execution import load_execution
    record = load_execution(rundir)["stages"].get(stage)
    if not isinstance(record, dict) or record.get("attempt_id") != attempt_id:
        raise ValueError(f"no execution receipt stage:{stage}:{attempt_id}")
    return record


def register_stage_receipt(rundir, stage, attempt_id):
    """Register a stage receipt after a supervised successful finish. Called by the stage
    supervisor, never by the bare ``execution.finish_attempt`` library function."""
    record = _stage_record(rundir, stage, attempt_id)
    if record.get("status") != "succeeded":
        raise ValueError(f"stage {stage} attempt {attempt_id} did not succeed")
    return append(rundir, "stages", {"stage": stage, "attempt_id": attempt_id, "record_sha256": _digest(record)})


def stage_receipt_registered(rundir, stage, attempt_id, record):
    digest = _digest(record)
    return any(r["record"] == {"stage": stage, "attempt_id": attempt_id, "record_sha256": digest}
               for r in rows(rundir, "stages"))
