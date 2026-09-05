#!/usr/bin/env python3
"""workflow_state.py -- the LIVE per-run state machine (the keystone ledger).

Writes and drives <rundir>/run_state.json: the single source of truth for which skills were
invoked, what compute was launched, which subagents ran, what was edited, and -- via `advance` --
how far the lifecycle has progressed. The PostToolUse observer (and its step-doc fallback twin)
call `record`; every later gate (DRIVE, skill-coverage, phantom-bg, provenance) READS this file.

Reuses validate_run_state.py's declarative lifecycle model (STAGE_ORDER / STAGE_MATRIX /
resolve_level / evaluate) so `advance` refuses to move past a stage whose required predecessors are
not satisfied -- the post-hoc judge turned into a live driver.

Usage:
  workflow_state.py init    --rundir <dir> [--session-id <id>] [--force]
  workflow_state.py record  (--rundir <dir> | --project-dir <dir>) --kind skill|compute|subagent|edit --payload <json>
  workflow_state.py advance --rundir <dir> --to <stage> [--json]
  workflow_state.py status  --rundir <dir> [--json]
  workflow_state.py next    --rundir <dir> [--json]
  workflow_state.py require --rundir <dir> --kind skill|command|artifact|stage --what <str>
  workflow_state.py --selftest

Exit codes: 0 OK * 1 precondition/require FAIL * 2 usage / not-a-dir / bad payload * 3 no|invalid contract
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import json
import os
import sys
from functools import wraps
from pathlib import Path
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from ravel.workflow import provenance               # noqa: E402
from ravel.workflow import session_lock             # noqa: E402
from ravel.validation import validate_run_state       # noqa: E402
from ravel.validation import validate_task_contract   # noqa: E402
from ravel.workflow.state_io import atomic_json, file_lock, read_json

RUN_STATE_NAME = "run_state.json"
SCHEMA_VERSION = 1
GENERATOR = "workflow_state.py"

# every appendable list-key present at init so no downstream reader KeyErrors on a fresh ledger
LIST_KEYS = ("skills_invoked", "compute_launched", "subagents", "edits",
             "obligations", "open_failure_records", "open_defect_notes",
             "armed_watchers", "checkins")


def _state_path(rundir):
    return os.path.join(rundir, RUN_STATE_NAME)


def load_state(rundir):
    """Return (state_dict, err). err is a str on failure, else None."""
    p = _state_path(rundir)
    if not os.path.isfile(p):
        return None, f"no {RUN_STATE_NAME} in {rundir} (run `workflow_state.py init` first)"
    try:
        state = read_json(p)
        if not isinstance(state, dict):
            raise ValueError("run state must be an object")
        return state, None
    except (OSError, ValueError) as e:
        return None, f"cannot read/parse {RUN_STATE_NAME}: {e}"


class StateConflict(ValueError):
    """The caller read an older revision; re-read before changing the ledger."""


def write_state(rundir, state, *, replace=False):
    """Serialize writers and reject lost updates; keep forced reset evidence."""
    path = Path(_state_path(rundir))
    with file_lock(Path(rundir) / "logs/state/write.lock"):
        current = read_json(path) if path.exists() else {}
        expected = state.get("revision", 0)
        actual = current.get("revision", 0)
        if type(expected) is not int or type(actual) is not int:
            raise ValueError("state revision must be an integer")
        if not replace and actual != expected:
            raise StateConflict(f"run state changed: expected revision {expected}, found {actual}")
        if replace and current:
            from ravel.workflow.execution import utc_now
            backup = Path(rundir) / "logs/state" / f"revision-{actual}-{time.time_ns()}.json"
            atomic_json(backup, {"archived_utc": utc_now(), "state": current})
        updated = {**state, "revision": actual + 1}
        atomic_json(path, updated)
        state["revision"] = updated["revision"]


def retry_conflict(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(12):
            try:
                return function(*args, **kwargs)
            except StateConflict:
                if attempt == 11:
                    print("workflow_state: concurrent updates did not settle; retry this operation",
                          file=sys.stderr)
                    return 3
                time.sleep(0.005 * (attempt + 1))
    return wrapped


def new_state(rundir, contract, contract_path, session_id):
    """Build a fresh run_state dict with EVERY schema key populated (lists empty). SHARED §C."""
    state = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id or "",
        "task_mode": contract.get("task_mode"),
        "stat_mode": contract.get("stat_mode"),
        "detector_mode": contract.get("detector_mode"),
        "compute_plan": contract.get("compute_plan"),
        "current_step": None,
        "ladder_rung": None,
        "cursor_utc": provenance._resolve_timestamp(),
        "routed": False,
        "next_required": None,
    }
    for k in LIST_KEYS:
        state[k] = []
    state.update(provenance.provenance_pair(GENERATOR, [os.path.abspath(contract_path)]))
    return state


def cmd_init(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state init: not a directory: {rundir}", file=sys.stderr)
        return 2
    if os.path.isfile(_state_path(rundir)) and not args.force:
        print(f"workflow_state init: {RUN_STATE_NAME} already exists in {rundir} "
              "(use --force to overwrite)", file=sys.stderr)
        return 3
    contract, cpath, err = validate_run_state.load_contract_for(rundir, None)
    if err:
        print(f"workflow_state init: {err}", file=sys.stderr)
        return 3
    errs = validate_task_contract.validate(contract)
    if errs:
        print("workflow_state init: task_contract.json is invalid:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 3
    state = new_state(rundir, contract, cpath, args.session_id)
    write_state(rundir, state, replace=args.force)
    print(f"workflow_state: initialized {_state_path(rundir)} "
          f"(task_mode={state['task_mode']}, compute_plan={state['compute_plan']})")
    return 0


def _norm_skill(p):
    if "skill" not in p:
        raise ValueError("skill payload requires a 'skill' field")
    return {"skill": p["skill"]}


def _norm_compute(p):
    if "cmd" not in p:
        raise ValueError("compute payload requires a 'cmd' field")
    return {
        "cmd": p["cmd"],
        "bg_kind": p.get("bg_kind"),
        "bg_id": p.get("bg_id"),
        "logfile": p.get("logfile"),
        "done_condition": p.get("done_condition"),
        "next_action": p.get("next_action"),
        "supervised": bool(p.get("supervised", False)),
    }


def _norm_subagent(p):
    return {"agent_type": p.get("agent_type", "")}


def _norm_edit(p):
    if "path" not in p:
        raise ValueError("edit payload requires a 'path' field")
    return {"path": p["path"]}


# --- state-mutator kinds (D-3): list_key is None, so the normalizer takes (state, payload, utc)
#     and mutates `state` directly rather than returning a dict to append. These are the real
#     writers of `routed` + `open_failure_records`; Phase 2 INVOKES them. Return True iff state
#     was mutated -- False tells cmd_record to skip the write entirely (CR-135).
def _norm_route(state, payload, utc):
    """route: mark the run routed and leave an audit entry carrying the chosen route/target (via
    --payload {"route":...} or the --what shortcut). A payload with NO routing content is a silent
    no-op (CR-135): the router hook fires this blind on every physics-looking prompt, and a
    contentless append is pure ledger noise ({"utc": ""} rows) whose rewrite also refreshes the
    file mtime -- the loop that kept a closed run looking 'active' forever."""
    audit = {"utc": utc}
    for k in ("route", "next", "what"):
        if payload.get(k):
            audit[k] = payload[k]
    if len(audit) == 1:
        return False
    state["routed"] = True
    state.setdefault("routes", []).append(audit)
    return True


def _norm_failure(state, payload, utc):
    """failure: register an OPEN failure record -- the logs/<stage>.failure.json relpath
    stage_supervisor.py just wrote -- so the CATCH fallback + Stop open-failure branch can see it.
    Requires the relpath (via --what, or --payload {"ref"|"path": ...}); de-duplicates."""
    ref = payload.get("ref") or payload.get("path") or payload.get("what")
    if not ref:
        raise ValueError("failure payload requires the failure.json relpath (--what or 'ref')")
    open_recs = state.setdefault("open_failure_records", [])
    if ref not in open_recs:
        open_recs.append(ref)
    return True


# kind -> (run_state list key, payload normalizer). Later phases register new kinds here.
# A str list_key => list-append kind (normalizer (payload)->dict); None => state-mutator kind
# (normalizer (state, payload, utc) mutates state).
RECORD_KINDS = {
    "skill":    ("skills_invoked",   _norm_skill),
    "compute":  ("compute_launched", _norm_compute),
    "subagent": ("subagents",        _norm_subagent),
    "edit":     ("edits",            _norm_edit),
    "route":    (None,               _norm_route),      # D-3: sets state["routed"]=True
    "failure":  (None,               _norm_failure),    # D-3: appends to open_failure_records
}


# liveness window for the SESSION.lock heartbeat; matches session_lock's --stale-hours default
LOCK_FRESH_HOURS = 24.0


def _rundir_is_active(rundir, fresh_hours=LOCK_FRESH_HOURS):
    """A rundir counts as ACTIVE for auto-resolution iff it is not closed (no RESULT.md -- the
    run's closing record) and carries the CR-022 ownership mark: a SESSION.lock with a heartbeat
    inside fresh_hours. NOT ledger-mtime freshness -- that rule is unsound: any maintenance write
    to a stale ledger (even a noise scrub) resurrects it, and each misdirected append then keeps
    it fresh forever. Runtime-only wall-clock comparison (like session_lock itself) -- nothing
    here is recorded, so the no-datetime.now() emitter rule is not in play."""
    if os.path.isfile(os.path.join(rundir, "RESULT.md")):
        return False
    lock = session_lock._read(os.path.join(rundir, session_lock.LOCK))
    return bool(lock) and \
        session_lock._age_hours(lock.get("renewed", lock.get("acquired", ""))) < fresh_hours


def find_active_rundir(project_dir):
    """Resolve the ledger `record --project-dir` (the observer + router hooks) should append to.
    Resolution order (CR-135):
      1. cwd inside a trial-runs/* rundir that has a run_state.json -> that rundir (the session is
         working IN that run -- unambiguous, even for a closed run being backfilled);
      2. else the newest trial-runs/*/run_state.json among ACTIVE rundirs (live SESSION.lock, no
         RESULT.md -- see _rundir_is_active) -> its rundir;
      3. else None (record self-scopes to a no-op).
    'Active' used to mean just 'newest mtime', which matched long-closed runs forever -- every
    misdirected append refreshed the mtime that made the run look newest (the D-3 route-noise
    class, the {"utc": ""} rows in closed runs' ledgers)."""
    base = os.path.join(project_dir, "trial-runs")
    base_abs = os.path.abspath(base)
    cwd = os.path.abspath(os.getcwd())
    if cwd.startswith(base_abs + os.sep):
        name = cwd[len(base_abs) + 1:].split(os.sep)[0]
        rd = os.path.join(base, name)
        if os.path.isfile(os.path.join(rd, RUN_STATE_NAME)):
            return rd
    best, best_mtime = None, -1.0
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    for name in entries:
        rd = os.path.join(base, name)
        cand = os.path.join(rd, RUN_STATE_NAME)
        try:
            m = os.path.getmtime(cand)
        except OSError:
            continue
        if m > best_mtime and _rundir_is_active(rd):
            best, best_mtime = rd, m
    return best


@retry_conflict
def cmd_record(args):
    rundir = args.rundir
    if rundir is None:
        if not args.project_dir:
            print("workflow_state record: need --rundir or --project-dir", file=sys.stderr)
            return 2
        rundir = find_active_rundir(args.project_dir)
        if rundir is None:
            return 0                    # observer best-effort: no active run -> no-op, never block
    rundir = rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state record: not a directory: {rundir}", file=sys.stderr)
        return 2
    if args.payload is not None:
        try:
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except ValueError as e:
            print(f"workflow_state record: bad --payload: {e}", file=sys.stderr)
            return 2
    elif args.what is not None:
        payload = {"what": args.what}     # --what shortcut for string-valued kinds (route/failure)
    else:
        payload = {}                      # e.g. a bare `record --kind route`; the normalizer decides
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state record: {err}", file=sys.stderr)
        return 3
    list_key, norm = RECORD_KINDS[args.kind]
    utc = provenance._resolve_timestamp()
    try:
        if list_key is None:                          # state-mutator kind (route/failure)
            if not norm(state, payload, utc):
                return 0                              # nothing recorded -> no write, no mtime touch
        else:                                         # list-append kind (skill/compute/subagent/edit)
            entry = norm(payload)
            entry["utc"] = utc
            state.setdefault(list_key, []).append(entry)
    except ValueError as e:
        print(f"workflow_state record: {e}", file=sys.stderr)
        return 2
    state["cursor_utc"] = utc
    write_state(rundir, state)
    return 0


def _prev_stage(stage):
    i = validate_run_state.STAGE_ORDER.index(stage)
    return validate_run_state.STAGE_ORDER[i - 1] if i > 0 else None


def compute_next_required(rundir, contract):
    """The FIRST required stage not yet PASSing, as a next-action hint, else None when the full
    required prefix is satisfied. Read-only (reuses validate_run_state.evaluate)."""
    from ravel.workflow.execution import validate_execution
    execution_errors = validate_execution(rundir)
    if execution_errors:
        return {"kind": "execution", "what": "repair or resume invalid stage",
                "why": "; ".join(execution_errors)}
    result = validate_run_state.evaluate(rundir, contract)
    for stage in result["stages"]:
        if stage["required"] == "R" and stage["status"] not in ("PASS", "N/A", "waived-legacy"):
            return {"kind": "artifact", "what": stage["name"],
                    "why": f"required stage {stage['name']!r} is {stage['status']}"}
    for invariant in result["invariants"]:
        if invariant["status"] == "FAIL":
            return {"kind": "invariant", "what": invariant["name"], "why": invariant["detail"]}
    return None


@retry_conflict
def cmd_advance(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state advance: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state advance: {err}", file=sys.stderr)
        return 3
    contract, _cpath, cerr = validate_run_state.load_contract_for(rundir, None)
    if cerr:
        print(f"workflow_state advance: {cerr}", file=sys.stderr)
        return 3
    target = args.to
    prev = _prev_stage(target)
    blockers = validate_task_contract.validate(contract)
    if prev is not None and not blockers:
        result = validate_run_state.evaluate(rundir, contract, stage_limit=prev)
        for s in result["stages"]:
            if s["status"] == "FAIL":
                blockers.append(f"stage {s['name']}: FAIL ({s['status']})")
        for inv in result["invariants"]:
            if inv["status"] == "FAIL":
                blockers.append(f"invariant {inv['name']}: {inv['detail']}")
    payload = {"target": target, "blockers": blockers}
    if blockers:
        payload["advanced"] = False
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"workflow_state advance: REFUSED advance to {target!r} -- unmet preconditions:",
                  file=sys.stderr)
            for b in blockers:
                print(f"  - {b}", file=sys.stderr)
        return 1
    state["current_step"] = target
    state["cursor_utc"] = provenance._resolve_timestamp()
    state["next_required"] = compute_next_required(rundir, contract)
    write_state(rundir, state)
    payload["advanced"] = True
    payload["next_required"] = state["next_required"]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        nr = state["next_required"]
        print(f"workflow_state advance: now at {target!r}; next_required="
              f"{nr['what'] if nr else '(none -- required prefix satisfied)'}")
    return 0


APPROVAL_VERSION = 2
APPROVAL_GENERATOR = "workflow_state.py approve"
APPROVAL_PLANS = ("none", "dry", "smoke", "full", "scan")


def approval_input_paths(rundir):
    """The single ordered input binding, shared by approval emission and verification."""
    rel = validate_run_state.find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json")
    return [os.path.join(rundir, rel or "inputs/task_contract.json"),
            os.path.join(rundir, "inputs", "checkin1.json"),
            os.path.join(rundir, "inputs", "cost_preflight.json")]


def verify_approval(rundir, record=None, *, required_plan=None):
    """Return strict live-approval errors. This checks integrity, not human identity.

    Version-1 approvals have no content binding and must be re-recorded before live
    compute. No legacy waiver is available here. All declared source bytes must still
    match the canonical provenance fingerprint captured by the approve command.
    """
    if record is None:
        try:
            record = validate_task_contract.load_contract(
                os.path.join(rundir, "inputs", "checkin1_approval.json"))
        except (OSError, ValueError, UnicodeError, RecursionError) as e:
            return [f"checkin1_approval.json cannot be read: {e}"]
    if type(record) is not dict:
        return ["checkin1_approval.json must be an object"]
    fields = {"schema_version", "generated_by", "generated_utc", "approved_plan", "quote",
              "task_contract", "checkin1", "cost_preflight", "input_fingerprint"}
    errors = [f"approval missing required field {key!r}" for key in sorted(fields - record.keys())]
    errors += [f"approval has unknown field {key!r}" for key in record.keys() - fields]
    if type(record.get("schema_version")) is not int or record.get("schema_version") != APPROVAL_VERSION:
        errors.append("approval schema_version must be integer 2; unbound version-1 archives "
                      "must be re-recorded with workflow_state.py approve before live compute")
    for key in fields - {"schema_version"}:
        value = record.get(key)
        if type(value) is not str or (key != "generated_utc" and not value.strip()):
            errors.append(f"approval.{key} must be a " + ("string" if key == "generated_utc" else "nonblank string"))
    if errors:
        return errors
    if record["generated_by"] != APPROVAL_GENERATOR:
        errors.append(f"approval.generated_by must be {APPROVAL_GENERATOR!r}")
    plan = record["approved_plan"]
    if plan not in APPROVAL_PLANS:
        errors.append("approval.approved_plan must be none|dry|smoke|full|scan")
    if required_plan is not None:
        if required_plan not in APPROVAL_PLANS:
            errors.append("required_plan must be none|dry|smoke|full|scan")
        elif plan in APPROVAL_PLANS and (
                APPROVAL_PLANS.index(plan) < APPROVAL_PLANS.index(required_plan)):
            errors.append(f"explicit {required_plan} launch exceeds approved_plan={plan}")
    paths = approval_input_paths(rundir)
    for key, path in zip(("task_contract", "checkin1", "cost_preflight"), paths):
        if record[key] != os.path.relpath(path, rundir):
            errors.append(f"approval.{key} must name {os.path.relpath(path, rundir)!r}")
    if errors:
        return errors
    contract, _cpath, error = validate_run_state.load_contract_for(rundir, None)
    errors = [error] if error else validate_task_contract.validate(contract)
    if errors:
        return ["invalid task_contract.json: " + "; ".join(errors)]
    ladder = ("none", "dry", "smoke", "full", "scan")
    if ladder.index(plan) > ladder.index(contract["compute_plan"]):
        return [f"approved plan={plan} exceeds task_contract compute_plan={contract['compute_plan']}"]
    try:
        from ravel.validation import validate_checkin
        checkin = validate_task_contract.load_contract(paths[1])
        errors = validate_checkin.validate(checkin, base_dir=rundir)
        if type(checkin) is dict:
            if type(checkin.get("schema_version")) is not int:
                errors.append("checkin1.schema_version must be an exact integer")
            if checkin.get("kind") != "checkin1":
                errors.append("checkin1.kind must be checkin1")
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        errors = [str(e)]
    if errors:
        return ["invalid checkin1.json: " + "; ".join(errors)]
    try:
        budget = validate_task_contract.load_contract(paths[2])
        errors = validate_task_contract.validate(
            {**contract, "compute_plan": plan, "cost_estimate": budget})
        if type(budget) is dict and (type(budget.get("schema_version")) is not int
                                    or budget.get("schema_version") != 1
                                    or budget.get("generated_by") != "cost_preflight.py"):
            errors.append("cost artifact requires schema_version=1 and generated_by=cost_preflight.py")
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        errors = [str(e)]
    if errors:
        return ["invalid cost_preflight.json: " + "; ".join(errors)]
    matches, reason = provenance.verify_pair(record, APPROVAL_GENERATOR, paths)
    if not matches:
        return ["stale or unbound approval: " + reason + "; re-record approval for the current inputs"]
    return []


@retry_conflict
def cmd_approve(args):
    """Record a v2 approval bound to the contract, CHECK-IN 1, and budget bytes."""
    rd = args.rundir.rstrip("/")
    if not os.path.isdir(rd):
        print(f"workflow_state approve: not a directory: {rd}", file=sys.stderr)
        return 2
    paths = approval_input_paths(rd)
    # Fingerprint BEFORE validation; verify_approval recomputes after all reads. An edit
    # during validation cannot silently become part of the newly recorded approval.
    rec = {"schema_version": APPROVAL_VERSION,
           "generated_utc": os.environ.get("WORKFLOW_STATE_UTC", ""),
           "approved_plan": args.plan, "quote": args.quote,
           "task_contract": os.path.relpath(paths[0], rd),
           "checkin1": "inputs/checkin1.json", "cost_preflight": "inputs/cost_preflight.json",
           **provenance.provenance_pair(APPROVAL_GENERATOR, paths)}
    errors = verify_approval(rd, rec)
    if errors:
        print("workflow_state approve: REFUSED -- " + "; ".join(errors), file=sys.stderr)
        return 1
    out = os.path.join(rd, "inputs", "checkin1_approval.json")
    atomic_json(out, rec)
    state, _ = load_state(rd)
    if state is not None:
        state.setdefault("checkins", []).append(
            {"id": "CHECKIN1-APPROVAL", "artifact": "inputs/checkin1_approval.json",
             "utc": rec["generated_utc"]})
        write_state(rd, state)
    print(f"approval recorded -> {out} (plan={args.plan})")
    return 0


def cmd_status(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state status: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state status: {err}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(f"run_state: {_state_path(rundir)}")
        print(f"  task_mode={state.get('task_mode')} compute_plan={state.get('compute_plan')} "
              f"routed={state.get('routed')}")
        print(f"  current_step={state.get('current_step')} ladder_rung={state.get('ladder_rung')}")
        for k in LIST_KEYS:
            print(f"  {k}: {len(state.get(k) or [])}")
        nr = state.get("next_required")
        print(f"  next_required={nr['what'] if nr else None}")
    return 0


def cmd_next(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state next: not a directory: {rundir}", file=sys.stderr)
        return 2
    _state, err = load_state(rundir)
    if err:
        print(f"workflow_state next: {err}", file=sys.stderr)
        return 3
    contract, _cpath, cerr = validate_run_state.load_contract_for(rundir, None)
    if cerr:
        print(f"workflow_state next: {cerr}", file=sys.stderr)
        return 3
    nr = compute_next_required(rundir, contract)
    if args.json:
        print(json.dumps(nr, indent=2))
    else:
        print(nr["what"] if nr else "(none -- required prefix satisfied)")
    return 0


def cmd_require(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state require: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state require: {err}", file=sys.stderr)
        return 3
    kind, what = args.kind, args.what
    ok = False
    if kind == "skill":
        ok = any(e.get("skill") == what for e in state.get("skills_invoked") or [])
    elif kind == "command":
        ok = any(what in (e.get("cmd") or "") for e in state.get("compute_launched") or [])
    elif kind == "artifact":
        ok = os.path.isfile(os.path.join(rundir, what))
    elif kind == "stage":
        contract, _c, cerr = validate_run_state.load_contract_for(rundir, None)
        if cerr:
            print(f"workflow_state require: {cerr}", file=sys.stderr)
            return 3
        ok = validate_run_state.evaluate(rundir, contract, stage_limit=what)["exit"] == 0
    if ok:
        print(f"workflow_state require: OK ({kind}={what!r} satisfied)")
        return 0
    print(f"workflow_state require: FAIL ({kind}={what!r} not satisfied)", file=sys.stderr)
    return 1


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--rundir", required=True)
    pi.add_argument("--session-id", default="")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("record")
    pr.add_argument("--rundir")
    pr.add_argument("--project-dir")
    pr.add_argument("--kind", required=True, choices=sorted(RECORD_KINDS))
    pr.add_argument("--payload")                 # JSON object (skill/compute/subagent/edit)
    pr.add_argument("--what")                    # string shortcut for route/failure
    pr.set_defaults(func=cmd_record)

    pa = sub.add_parser("advance")
    pa.add_argument("--rundir", required=True)
    pa.add_argument("--to", required=True, choices=validate_run_state.STAGE_ORDER)
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_advance)

    pv = sub.add_parser("approve")
    pv.add_argument("--rundir", required=True)
    pv.add_argument("--quote", required=True,
                    help="the physicist's go-ahead reply, quoted verbatim")
    pv.add_argument("--plan", default="smoke", choices=APPROVAL_PLANS)
    pv.set_defaults(func=cmd_approve)

    ps = sub.add_parser("status")
    ps.add_argument("--rundir", required=True)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_status)

    pn = sub.add_parser("next")
    pn.add_argument("--rundir", required=True)
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next)

    pq = sub.add_parser("require")
    pq.add_argument("--rundir", required=True)
    pq.add_argument("--kind", required=True, choices=("skill", "command", "artifact", "stage"))
    pq.add_argument("--what", required=True)
    pq.set_defaults(func=cmd_require)
    return ap


def selftest():
    import tempfile
    fails = []

    def check(label, ok, detail=""):
        print(f"[selftest] {label}: {detail}  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(label)

    def _survey_rundir(td):
        rd = os.path.join(td, "run")
        os.makedirs(os.path.join(rd, "inputs"))
        contract = {"schema_version": 1, "prompt": "selftest", "task_mode": "survey", "detector_mode": "particle-level",
                    "stat_mode": "none-survey", "required_user_inputs": [], "assumptions": ["fx"],
                    "compute_plan": "none", "approval_required": True}
        with open(os.path.join(rd, "inputs", "task_contract.json"), "w") as fh:
            json.dump(contract, fh)
        return rd

    with tempfile.TemporaryDirectory(prefix="workflow_state_selftest_") as td:
        rd = _survey_rundir(td)
        rc = main(["init", "--rundir", rd])
        state, err = load_state(rd)
        ok = rc == 0 and err is None and state is not None
        check("1 init writes run_state", ok, f"rc={rc}")
        if ok:
            check("2 init populates every schema key",
                  all(k in state for k in LIST_KEYS) and state["generated_by"] == GENERATOR
                  and len(state["input_fingerprint"]) == 64 and state["task_mode"] == "survey")
            check("3 init refuses to clobber", main(["init", "--rundir", rd]) == 3)
        # --- record ---
        assert main(["record", "--rundir", rd, "--kind", "skill",
                     "--payload", json.dumps({"skill": "physicist-intake"})]) == 0
        s2, _ = load_state(rd)
        check("4 record appends skill", [e.get("skill") for e in s2["skills_invoked"]] == ["physicist-intake"])
        check("5 record bad payload exits 2",
              main(["record", "--rundir", rd, "--kind", "edit", "--payload", "{}"]) == 2)
        # route/failure state-mutator kinds -- the real writers of routed + open_failure_records (D-3)
        check("5a record route flips routed",
              main(["record", "--rundir", rd, "--kind", "route", "--what", "reproduce"]) == 0
              and load_state(rd)[0]["routed"] is True)
        check("5b record failure registers open_failure_records",
              main(["record", "--rundir", rd, "--kind", "failure", "--what", "logs/gen.failure.json"]) == 0
              and load_state(rd)[0]["open_failure_records"] == ["logs/gen.failure.json"])
        # CR-135: a route record with no routing content is a silent no-op (no row, no rewrite)
        _pre = open(_state_path(rd), "rb").read()
        check("5c record route without content is a no-op",
              main(["record", "--rundir", rd, "--kind", "route"]) == 0
              and open(_state_path(rd), "rb").read() == _pre)
        # --- advance ---
        check("6 advance to resource_census allowed",
              main(["advance", "--rundir", rd, "--to", "resource_census"]) == 0)
        check("7 advance to route refused (census/trap_sweep unmet)",
              main(["advance", "--rundir", rd, "--to", "route"]) == 1)
        # --- require (fallback gate) ---
        # NB: use a skill NOT recorded by any earlier selftest case -- case 4 already recorded
        # 'physicist-intake' into this SHARED rundir, so the first `require` on it would return 0.
        # 'verification-panel' is unrecorded here, so the first require legitimately FAILs (exit 1).
        check("8 require skill FAIL then PASS after record",
              main(["require", "--rundir", rd, "--kind", "skill", "--what", "verification-panel"]) == 1
              and main(["record", "--rundir", rd, "--kind", "skill",
                        "--payload", json.dumps({"skill": "verification-panel"})]) == 0
              and main(["require", "--rundir", rd, "--kind", "skill", "--what", "verification-panel"]) == 0)
        check("9 require stage route refused",
              main(["require", "--rundir", rd, "--kind", "stage", "--what", "route"]) == 1)
        check("10 status/next read-only exit 0",
              main(["status", "--rundir", rd]) == 0 and main(["next", "--rundir", rd]) == 0)

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("workflow_state selftest: PASS")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
